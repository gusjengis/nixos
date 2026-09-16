set -euo pipefail

probe_timeout="${TAILNET_THUNAR_PROBE_TIMEOUT:-10}"
refresh_interval="${TAILNET_THUNAR_REFRESH_INTERVAL:-5}"
full_refresh_interval="${TAILNET_THUNAR_FULL_REFRESH_INTERVAL:-60}"
office_gateway="${TAILNET_THUNAR_OFFICE_GATEWAY:-mac.tail29bd65.ts.net}"
og_host="${TAILNET_THUNAR_OG_HOST:-pc.tail29bd65.ts.net}"
og_address="${TAILNET_THUNAR_OG_ADDRESS:-192.168.122.18}"
og_share="${TAILNET_THUNAR_OG_SHARE:-WindowsRoot}"
og_user="${TAILNET_THUNAR_OG_USER:-antho}"

config_home="${XDG_CONFIG_HOME:-$HOME/.config}"
state_home="${XDG_STATE_HOME:-$HOME/.local/state}"
bookmarks_file="$config_home/gtk-3.0/bookmarks"
state_dir="$state_home/tailnet-thunar-bookmarks"
managed_file="$state_dir/managed-bookmarks"
status_hash_file="$state_dir/status-hash"
refresh_lock_file="$state_dir/refresh.lock"

bookmark_label() {
  local host="$1"
  host="${host%%.*}"
  printf '%s (Tailnet)' "$host"
}

peer_lines() {
  local status_json="$1"

  jq -r '
    .Self.DNSName as $self |
    .Peer[]? |
    select(.DNSName != null and .DNSName != "" and .DNSName != $self) |
    .DNSName |
    sub("[.]$"; "")
  ' "$status_json" | sort -u
}

probe_peer() {
  local host="$1"

  if nc -z -w "$probe_timeout" "$host" 22 >/dev/null 2>&1; then
    printf 'sftp://%s/ %s\n' "$host" "$(bookmark_label "$host")"
  fi
}

office_gateway_ready() {
  local status_json="$1"

  jq -e --arg gateway "$office_gateway" '
    def clean_name: sub("[.]$"; "");

    (.BackendState == "Running") and (
      ((.Self.DNSName // "" | clean_name) == $gateway) or
      any(
        .Peer[]?;
        ((.DNSName // "" | clean_name) == $gateway) and
        (.Online == true) and
        ((.AllowedIPs // []) | index("10.145.0.15/32") != null) and
        ((.AllowedIPs // []) | index("10.145.0.18/32") != null)
      )
    )
  ' "$status_json" >/dev/null
}

is_cifs_mounted() {
  local path="$1"

  findmnt --kernel --raw --noheadings --types cifs --output TARGET | grep -Fqx -- "$path"
}

append_office_bookmarks() {
  local status_json="$1"
  local new_managed="$2"

  office_gateway_ready "$status_json" || return 0

  if is_cifs_mounted /mnt/office/orthos; then
    printf 'file:///mnt/office/orthos O: Orthos\n' >> "$new_managed"
  fi

  if is_cifs_mounted /mnt/office/company; then
    printf '%s\n' \
      'file:///mnt/office/company/Users U: Users' \
      'file:///mnt/office/company/Jobs X: Jobs' \
      'file:///mnt/office/company/Jobs%20Archive Y: Jobs Archive' \
      'file:///mnt/office/company/Admin Z: Admin' \
      >> "$new_managed"
  fi
}

# The OG VM lives on the libvirt network of og_host and is only meaningful when
# this machine is that host, or when that host advertises the route to it.
# Without this gate another machine's own virbr0 could answer at the same
# address and produce a bookmark pointing at the wrong system.
og_route_available() {
  local status_json="$1"

  jq -e --arg host "$og_host" --arg route "$og_address/32" '
    def clean_name: sub("[.]$"; "");

    (.BackendState == "Running") and (
      ((.Self.DNSName // "" | clean_name) == $host) or
      any(
        .Peer[]?;
        ((.DNSName // "" | clean_name) == $host) and
        (.Online == true) and
        ((.AllowedIPs // []) | index($route) != null)
      )
    )
  ' "$status_json" >/dev/null
}

# gvfs mounts smb:// lazily, so a stopped VM costs nothing. The bookmark is only
# published while the guest actually answers on SMB.
append_og_bookmark() {
  local status_json="$1"
  local new_managed="$2"

  og_route_available "$status_json" || return 0

  if nc -z -w "$probe_timeout" "$og_address" 445 >/dev/null 2>&1; then
    printf 'smb://%s@%s/%s OG (Windows)\n' "$og_user" "$og_address" "$og_share" >> "$new_managed"
  fi
}

write_bookmarks() {
  local new_managed="$1"
  local tmp_preserved tmp_next

  mkdir -p "$(dirname "$bookmarks_file")" "$state_dir"
  [ -e "$bookmarks_file" ] || touch "$bookmarks_file"
  [ -e "$managed_file" ] || touch "$managed_file"

  tmp_preserved="$(mktemp)"
  tmp_next="$(mktemp)"

  if [ -s "$managed_file" ]; then
    grep -F -x -v -f "$managed_file" "$bookmarks_file" \
      | grep -v '^file:///data/Literature\( \|$\)' \
      | grep -v '^$' > "$tmp_preserved" || true
  else
    grep -v '^file:///data/Literature\( \|$\)' "$bookmarks_file" \
      | grep -v '^$' > "$tmp_preserved" || true
  fi

  {
    cat "$tmp_preserved"
    if [ -s "$tmp_preserved" ] && [ -s "$new_managed" ]; then
      printf '\n'
    fi
    cat "$new_managed"
  } > "$tmp_next"

  if ! cmp -s "$tmp_next" "$bookmarks_file"; then
    install -m 0644 "$tmp_next" "$bookmarks_file"
  fi

  if ! cmp -s "$new_managed" "$managed_file"; then
    install -m 0644 "$new_managed" "$managed_file"
  fi
  rm -f "$tmp_preserved" "$tmp_next"
}

refresh_once_unlocked() {
  local status_json peers_file new_managed host

  mkdir -p "$state_dir"
  status_json="$(mktemp)"
  peers_file="$(mktemp)"
  new_managed="$(mktemp)"

  printf '%s\n' \
    'file:///data data' \
    'file:///data/Supernote Supernote' \
    > "$new_managed"

  if ! tailscale status --json > "$status_json" 2>/dev/null; then
    write_bookmarks "$new_managed"
    rm -f "$status_json" "$peers_file" "$new_managed"
    return 0
  fi

  peer_lines "$status_json" > "$peers_file"

  while IFS= read -r host; do
    [ -n "$host" ] || continue
    probe_peer "$host" >> "$new_managed" &
  done < "$peers_file"
  wait

  append_office_bookmarks "$status_json" "$new_managed"
  append_og_bookmark "$status_json" "$new_managed"

  sort -u -o "$new_managed" "$new_managed"
  write_bookmarks "$new_managed"
  rm -f "$status_json" "$peers_file" "$new_managed"
}

refresh_once() {
  mkdir -p "$state_dir"
  (
    flock 9
    refresh_once_unlocked
  ) 9> "$refresh_lock_file"
}

clear_managed() {
  local new_managed

  mkdir -p "$state_dir"
  (
    flock 9
    new_managed="$(mktemp)"
    write_bookmarks "$new_managed"
    rm -f "$new_managed" "$status_hash_file"
  ) 9> "$refresh_lock_file"
}

status_hash() {
  local status_json="$1"

  jq -r '
    [
      .Self.DNSName,
      (
        .Peer[]? |
        [
          .DNSName,
          .Online,
          .Active,
          .TailscaleIPs[0],
          (.AllowedIPs // [] | join(",")),
          (.PrimaryRoutes // [] | join(","))
        ] |
        @tsv
      )
    ] | @tsv
  ' "$status_json" | sha256sum | cut -d " " -f 1
}

watch() {
  local last_full now status_json current_hash previous_hash

  last_full=0
  while true; do
    mkdir -p "$state_dir"
    status_json="$(mktemp)"
    now="$(date +%s)"

    if tailscale status --json > "$status_json" 2>/dev/null; then
      current_hash="$(status_hash "$status_json")"
      previous_hash=""
      [ -f "$status_hash_file" ] && previous_hash="$(cat "$status_hash_file")"

      if [ "$current_hash" != "$previous_hash" ] || [ $((now - last_full)) -ge "$full_refresh_interval" ]; then
        refresh_once
        printf '%s\n' "$current_hash" > "$status_hash_file"
        last_full="$now"
      fi
    else
      refresh_once
      rm -f "$status_hash_file"
      last_full="$now"
    fi

    rm -f "$status_json"
    sleep "$refresh_interval"
  done
}

case "${1:-refresh}" in
  refresh)
    refresh_once
    ;;
  clear)
    clear_managed
    ;;
  watch)
    watch
    ;;
  *)
    printf 'Usage: %s [clear|refresh|watch]\n' "$0" >&2
    exit 2
    ;;
esac
