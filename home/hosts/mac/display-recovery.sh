# Re-apply the Hyprland monitor config whenever a connector's HPD cycles.
#
# Why this exists (mac only, Apple Silicon / Asahi):
#
# The M2 Pro HDMI port drives 3840x2160@120 over HDMI 2.1 FRL with DSC 1.2.
# That link is marginal, and the DCP firmware periodically tears it down on its
# own:
#
#   apple-dcp 289c00000.dcp: RTKit: syslog message: DCPAVService.cpp:954:
#     [AFK]Restaring interfaces with reason - FRL error rate exceeded..
#
# Switching the monitor off and on does the same thing. Either way HPD drops
# and reasserts. Aquamarine handles the drop correctly, but on the way back up
# its rescan sees
#
#   drm: Connector 70 connection state: 1
#   drm: Skipping connector HDMI-A-1, has crtc 68 and is connected
#
# so it reuses the existing CRTC and never issues a new modeset. DCP, however,
# threw its timings away, so it silently eats every frame:
#
#   IOMFB: swap_submit_dcp: swallowed swap ID N as timinsg are not enabled
#
# Every atomic commit then waits out the full 10 second flip_done timeout:
#
#   [drm] *ERROR* flip_done timed out
#   [drm] *ERROR* [CRTC:68:crtc-1] commit wait timed out
#
# Hyprland renders all outputs from one loop, so that stalls the internal panel
# too. The session looks hard-frozen until the external monitor is switched off
# and HPD drops again. Only a real modeset (set_digital_out_mode) clears it,
# which used to mean rebooting.
#
# Recovering means forcing the output down and back up so Hyprland cannot take
# the "already connected, nothing to do" path. Measured on this machine:
#
#   - `hyprctl reload` alone does nothing; the rule is unchanged, so there is
#     no state transition and no modeset.
#   - `force_renderer_reload` re-commits without dropping the CRTC. It does not
#     produce a modeset either, it just buys three more 10s timeouts.
#   - Disabling the output and then reloading *does* produce
#     `set_digital_out_mode` and brings the link back.
#
# Timing matters. Disabling an output that is already wedged has to drain the
# pending commits first and costs ~30s of flip_done timeouts. Disabling it at
# the moment HPD drops is free, because Hyprland has already stopped committing
# there. So the disconnect edge is where the real work happens; the connect
# edge just re-enables.

once=false
if [ "${1-}" = "--once" ]; then
	once=true
	shift
fi

connectors=("$@")
if [ ${#connectors[@]} -eq 0 ]; then
	echo "usage: display-recovery [--once] CONNECTOR..." >&2
	exit 64
fi

# Seconds to wait after HPD reasserts. The kernel already applies a 500ms HPD
# debounce and then runs dcp_dptx_connect(); reloading before that completes
# means modesetting against a half-initialised link.
settle=${DISPLAY_RECOVERY_SETTLE:-2}

# How long to wait on a single hyprctl call. Generous on purpose: if the
# compositor is mid-stall these block for tens of seconds, and giving up early
# would abandon the recovery halfway with the output still disabled.
call_timeout=${DISPLAY_RECOVERY_TIMEOUT:-90}

# Re-check sysfs at least this often even if no udev event arrives. udevadm
# block-buffers its stdout when it is not writing to a terminal, so events can
# sit unflushed in the pipe indefinitely. stdbuf below usually fixes that, but
# a connector that silently misses an edge is exactly the failure this whole
# script exists to prevent, so do not rely on it alone.
poll=${DISPLAY_RECOVERY_POLL:-2}

log() { echo "display-recovery: $*"; }

# systemd user services do not inherit HYPRLAND_INSTANCE_SIGNATURE (the
# compositor exports it into its own children only) and hyprctl refuses to
# guess. Find the instance that still owns a live control socket.
instance() {
	local dir
	for dir in "${XDG_RUNTIME_DIR:-/run/user/$(id -u)}"/hypr/*/; do
		[ -S "${dir}/.socket.sock" ] || continue
		basename "${dir}"
		return 0
	done
	return 1
}

# This Hyprland is a fork with a Lua config rather than hyprlang, so `hyprctl
# keyword` is not wired up: it answers "unknown request" and still exits 0.
# Everything here goes through the Lua bridge instead, and the reply is checked
# rather than trusted.
hypr() {
	local sig out rc=0
	if ! sig=$(instance); then
		log "no live Hyprland instance, skipping: hyprctl $*"
		return 1
	fi
	out=$(HYPRLAND_INSTANCE_SIGNATURE="${sig}" timeout "${call_timeout}" hyprctl "$@" 2>&1) || rc=$?
	if [ "${rc}" -ne 0 ]; then
		log "hyprctl $* failed (rc=${rc}): ${out}"
		return 1
	fi
	case ${out} in
	*"unknown request"* | *"didn't respond"* | error*)
		log "hyprctl $* rejected: ${out}"
		return 1
		;;
	esac
	return 0
}

# hl.monitor({ disabled = ... }) is the fork's equivalent of `monitor=NAME,disable`.
# See src/config/lua/bindings/LuaBindingsConfigRules.cpp, MONITOR_FIELDS.
disable_output() {
	hypr eval "hl.monitor({output=\"$1\", disabled=true})"
}

# Re-reads monitors.lua, so the mode stays defined in exactly one place. This
# is only a modeset because the output is currently disabled; see the header.
enable_output() {
	hypr reload
}

# Connector names are stable but the card index is not, so glob for it.
# Reading `status` is a cached read in drm_sysfs.c, not a probe, so polling it
# cannot itself disturb the link.
status_of() {
	local connector=$1 path
	for path in /sys/class/drm/*-"${connector}"/status; do
		if [ -r "${path}" ]; then
			cat "${path}"
			return 0
		fi
	done
	echo absent
}

# Unconditional down-then-up. Used by the keybind, and on the connect edge
# where the disable may not have happened yet.
recycle() {
	local connector=$1
	log "${connector}: forcing modeset"
	disable_output "${connector}" || return 1
	sleep 1
	enable_output || return 1
	log "${connector}: modeset applied"
}

if [ "${once}" = true ]; then
	rc=0
	for connector in "${connectors[@]}"; do
		recycle "${connector}" || rc=1
	done
	exit "${rc}"
fi

declare -A previous
for connector in "${connectors[@]}"; do
	previous[${connector}]=$(status_of "${connector}")
	log "watching ${connector} (currently ${previous[${connector}]})"
done

# Event-driven via udev, with the poll above as a backstop. Process
# substitution on fd 3 rather than a pipe, so the loop runs in this shell and
# `previous` survives between iterations.
exec 3< <(stdbuf -oL udevadm monitor --udev --subsystem-match=drm 2>/dev/null)

while true; do
	rc=0
	read -r -t "${poll}" _ <&3 || rc=$?
	# read returns 1 at EOF and >128 on timeout. EOF means udevadm died, which
	# would leave the machine without recovery, so exit and let systemd restart.
	if [ "${rc}" -eq 1 ]; then
		log "udev stream ended"
		exit 1
	fi

	for connector in "${connectors[@]}"; do
		now=$(status_of "${connector}")
		old=${previous[${connector}]}
		if [ "${now}" = "${old}" ]; then
			continue
		fi
		previous[${connector}]=${now}
		log "${connector}: ${old} -> ${now}"

		if [ "${now}" = disconnected ]; then
			# The cheap moment to disable: Hyprland has already stopped
			# committing here, so this cannot inherit a stuck commit. Doing it
			# now is what keeps the reconnect from costing 30s of timeouts.
			disable_output "${connector}" || true
		elif [ "${now}" = connected ]; then
			sleep "${settle}"
			# Full recycle rather than a bare reload. The disable above is not
			# guaranteed to have happened: the service may have started while
			# the connector was already disconnected, in which case Hyprland
			# still has the output enabled and a reload alone is a no-op that
			# would leave DCP without timings.
			recycle "${connector}" || true
		fi
	done
done
