#!/usr/bin/env bash
set -euo pipefail

REPO="${ROXANNE_REPO:-TylerIllman/Roxanne}"
VERSION_INPUT="${ROXANNE_VERSION:-}"
NO_OPEN="${ROXANNE_NO_OPEN:-}"

say() {
  printf '[roxanne-install] %s\n' "$*"
}

fail() {
  printf '[roxanne-install] Error: %s\n' "$*" >&2
  exit 1
}

need_command() {
  command -v "$1" >/dev/null 2>&1 || fail "Required command not found: $1"
}

normalize_tag() {
  local value="$1"
  if [[ -z "$value" ]]; then
    printf ''
  elif [[ "$value" == v* ]]; then
    printf '%s' "$value"
  else
    printf 'v%s' "$value"
  fi
}

latest_tag() {
  need_command curl
  local api_url="https://api.github.com/repos/${REPO}/releases/latest"
  local tag
  tag="$(
    curl -fsSL "$api_url" \
      | sed -n 's/.*"tag_name":[[:space:]]*"\([^"]*\)".*/\1/p' \
      | head -n 1
  )"
  [[ -n "$tag" ]] || fail "Could not determine the latest GitHub Release tag."
  printf '%s' "$tag"
}

asset_exists() {
  local url="$1"
  curl -fsIL -o /dev/null "$url"
}

download_asset() {
  local url="$1"
  local output_path="$2"
  say "Downloading $(basename "$output_path")"
  curl -fL --progress-bar "$url" -o "$output_path"
}

install_macos() {
  need_command curl
  need_command ditto
  need_command xattr
  need_command uname

  local arch
  case "$(uname -m)" in
    arm64|aarch64) arch="arm64" ;;
    x86_64) arch="x64" ;;
    *) fail "Unsupported macOS architecture: $(uname -m)" ;;
  esac

  local tag version asset_name asset_url
  tag="$(normalize_tag "$VERSION_INPUT")"
  [[ -n "$tag" ]] || tag="$(latest_tag)"
  version="${tag#v}"
  asset_name="Roxanne-${version}-mac-${arch}.zip"
  asset_url="https://github.com/${REPO}/releases/download/${tag}/${asset_name}"

  if ! asset_exists "$asset_url"; then
    fail "Release asset not found for this Mac (${asset_name}). Publish a matching macOS build first."
  fi

  local tmp_dir archive_path extract_dir app_bundle install_dir target_path
  tmp_dir="$(mktemp -d)"
  archive_path="${tmp_dir}/${asset_name}"
  extract_dir="${tmp_dir}/extracted"
  mkdir -p "$extract_dir"
  trap 'rm -rf "$tmp_dir"' EXIT

  download_asset "$asset_url" "$archive_path"
  ditto -x -k "$archive_path" "$extract_dir"

  app_bundle="$(find "$extract_dir" -maxdepth 2 -type d -name 'Roxanne.app' | head -n 1)"
  [[ -n "$app_bundle" ]] || fail "Downloaded archive did not contain Roxanne.app"

  if [[ -w /Applications ]]; then
    install_dir="/Applications"
  else
    install_dir="${HOME}/Applications"
    mkdir -p "$install_dir"
  fi

  target_path="${install_dir}/Roxanne.app"
  say "Installing Roxanne to ${target_path}"
  rm -rf "$target_path"
  ditto "$app_bundle" "$target_path"
  xattr -dr com.apple.quarantine "$target_path" || true

  if [[ -z "$NO_OPEN" ]]; then
    say "Opening Roxanne"
    open "$target_path"
  fi

  say "Done"
}

install_linux() {
  need_command curl
  need_command chmod
  need_command uname

  local arch
  case "$(uname -m)" in
    x86_64|amd64) arch="x86_64" ;;
    *) fail "Unsupported Linux architecture: $(uname -m). Only x86_64 AppImage builds are currently published." ;;
  esac

  local tag version asset_name asset_url
  tag="$(normalize_tag "$VERSION_INPUT")"
  [[ -n "$tag" ]] || tag="$(latest_tag)"
  version="${tag#v}"
  asset_name="Roxanne-${version}-linux-${arch}.AppImage"
  asset_url="https://github.com/${REPO}/releases/download/${tag}/${asset_name}"

  if ! asset_exists "$asset_url"; then
    fail "Release asset not found for this Linux system (${asset_name}). Publish a matching Linux build first."
  fi

  local install_root binary_path desktop_dir desktop_path icon_dir icon_path icon_url
  install_root="${HOME}/.local/opt/roxanne"
  binary_path="${install_root}/Roxanne.AppImage"
  desktop_dir="${HOME}/.local/share/applications"
  desktop_path="${desktop_dir}/roxanne.desktop"
  icon_dir="${HOME}/.local/share/icons/hicolor/1024x1024/apps"
  icon_path="${icon_dir}/roxanne.png"
  icon_url="https://raw.githubusercontent.com/${REPO}/main/apps/desktop/build/icon.png"

  mkdir -p "$install_root" "$desktop_dir" "$icon_dir" "${HOME}/.local/bin"
  download_asset "$asset_url" "$binary_path"
  chmod +x "$binary_path"

  curl -fsSL "$icon_url" -o "$icon_path" || true

  cat >"$desktop_path" <<EOF
[Desktop Entry]
Name=Roxanne
Comment=Local-first research copilot
Exec=${binary_path}
Terminal=false
Type=Application
Icon=${icon_path}
Categories=Office;Science;
EOF

  ln -sf "$binary_path" "${HOME}/.local/bin/roxanne"

  if command -v update-desktop-database >/dev/null 2>&1; then
    update-desktop-database "$desktop_dir" >/dev/null 2>&1 || true
  fi

  if [[ -z "$NO_OPEN" ]]; then
    say "Opening Roxanne"
    nohup "$binary_path" >/dev/null 2>&1 &
  fi

  say "Done"
}

main() {
  need_command uname

  case "$(uname -s)" in
    Darwin) install_macos ;;
    Linux) install_linux ;;
    *)
      fail "Unsupported platform: $(uname -s). Use the Windows PowerShell installer on Windows."
      ;;
  esac
}

main "$@"
