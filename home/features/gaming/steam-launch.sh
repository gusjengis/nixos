# Keep game launches quiet while allowing explicit client navigation.
steam_args=("$@")
silent=false
launch=false
for arg in "$@"; do
  case "$arg" in
    -silent) silent=true ;;
    -applaunch|steam://rungameid/*|steam://run/*|steam://launch/*) launch=true ;;
  esac
done
if "$launch" && ! "$silent"; then
  steam_args=(-silent "${steam_args[@]}")
fi
