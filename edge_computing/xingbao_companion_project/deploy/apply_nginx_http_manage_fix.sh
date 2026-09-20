#!/usr/bin/env bash
# Apply the Xingbao HTTP/manage routing fix to the board's Nginx config.
# Run as root on the board. The script is intentionally idempotent and keeps
# a timestamped backup beside the live configuration before reloading Nginx.
set -Eeuo pipefail

CONF_PATH="${1:-/etc/nginx/conf.d/xingbao.conf}"
NGINX_BIN="${NGINX_BIN:-nginx}"

if [[ "${EUID}" -ne 0 ]]; then
    echo "Run as root: sudo $0 [nginx-config-path]" >&2
    exit 1
fi

if [[ ! -f "${CONF_PATH}" ]]; then
    echo "Nginx config not found: ${CONF_PATH}" >&2
    exit 1
fi

if ! command -v "${NGINX_BIN}" >/dev/null 2>&1; then
    echo "nginx executable not found: ${NGINX_BIN}" >&2
    exit 1
fi

old_redirect='return 301 https://$host$request_uri;'
old_backend="defaultBackendURL: 'https://xingbao.wycspace.top/manage'"
new_backend="defaultBackendURL: '\$scheme://\$host/manage'"
new_manage_redirect='return 302 /manage/ui/;'
manage_auth_handler='location @xingbao_manage_basic_auth {'
manage_auth_error='error_page 401 = @xingbao_manage_basic_auth;'

candidate="$(mktemp "${CONF_PATH}.candidate.XXXXXX")"
backup="${CONF_PATH}.bak.$(date -u +%Y%m%dT%H%M%SZ)"
cleanup() {
    rm -f "${candidate}"
}
trap cleanup EXIT

cp --preserve=mode,ownership,timestamps "${CONF_PATH}" "${candidate}"

if grep -Fq "${old_redirect}" "${candidate}"; then
    # The first server in xingbao.conf is the HTTP-only redirect block. Remove
    # it and add its two listen directives to the existing TLS server so both
    # protocols share identical auth, proxy, and static-content locations.
    awk '
        BEGIN { skipping_http_server = 0; first_server_removed = 0; inserted_http_listeners = 0 }
        /^[[:space:]]*server[[:space:]]*\{[[:space:]]*$/ && first_server_removed == 0 {
            skipping_http_server = 1
            first_server_removed = 1
            next
        }
        skipping_http_server == 1 {
            if ($0 ~ /^[[:space:]]*\}[[:space:]]*$/) {
                skipping_http_server = 0
            }
            next
        }
        /^[[:space:]]*server[[:space:]]*\{[[:space:]]*$/ && inserted_http_listeners == 0 {
            print
            print ""
            print "    listen 80;"
            print "    listen [::]:80;"
            print ""
            inserted_http_listeners = 1
            next
        }
        { print }
        END {
            if (first_server_removed == 0 || inserted_http_listeners == 0) {
                exit 7
            }
        }
    ' "${candidate}" > "${candidate}.next"
    mv "${candidate}.next" "${candidate}"
fi

if grep -Fq "${old_backend}" "${candidate}"; then
    sed -i "s|${old_backend}|${new_backend}|" "${candidate}"
fi

# config.js must never preserve the old cross-protocol endpoint in a browser
# cache. The redirect from /manage/ is temporary for the same reason.
if ! sed -n '/^[[:space:]]*location = \/manage\/ui\/config\\.js[[:space:]]*{/,/^[[:space:]]*}[[:space:]]*$/p' "${candidate}" | grep -Fq 'Cache-Control "no-store, no-cache, must-revalidate" always;'; then
    sed -i '/sub_filter_types \*;/a\        add_header Cache-Control "no-store, no-cache, must-revalidate" always;' "${candidate}"
fi
sed -i 's|return 301 /manage/ui/;|return 302 /manage/ui/;|' "${candidate}"

# The site-wide 401 handler serves the Xingbao home login page, whose success
# path is '/'.  The management console uses a separate Basic-auth credential,
# so return its own 401 challenge instead of inheriting that home-page handler.
if ! grep -Fq "${manage_auth_handler}" "${candidate}"; then
    awk '
        BEGIN { inserted = 0 }
        /^[[:space:]]*location = \/manage\/[[:space:]]*\{[[:space:]]*$/ && inserted == 0 {
            print "    location @xingbao_manage_basic_auth {"
            print "        internal;"
            print "        return 401;"
            print "    }"
            print ""
            inserted = 1
        }
        { print }
        END { if (inserted != 1) exit 8 }
    ' "${candidate}" > "${candidate}.next"
    mv "${candidate}.next" "${candidate}"
fi

# auth_basic already supplies WWW-Authenticate. Remove the header used by an
# early version of this fix so browser clients receive one challenge only.
sed -i '/^[[:space:]]*add_header WWW-Authenticate /d' "${candidate}"

manage_error_count="$(grep -Fc "${manage_auth_error}" "${candidate}" || true)"
if [[ "${manage_error_count}" -lt 2 ]]; then
    awk '
        BEGIN { config_location = 0; manage_location = 0; config_added = 0; manage_added = 0 }
        /^[[:space:]]*location = \/manage\/ui\/config\.js[[:space:]]*\{[[:space:]]*$/ { config_location = 1 }
        /^[[:space:]]*location[[:space:]]+\/manage\/[[:space:]]*\{[[:space:]]*$/ { manage_location = 1 }
        config_location == 1 && /^[[:space:]]*auth_basic_user_file[[:space:]]+/ {
            print
            print "        error_page 401 = @xingbao_manage_basic_auth;"
            config_location = 0
            config_added += 1
            next
        }
        manage_location == 1 && /^[[:space:]]*auth_basic_user_file[[:space:]]+/ {
            print
            print "        error_page 401 = @xingbao_manage_basic_auth;"
            manage_location = 0
            manage_added += 1
            next
        }
        { print }
        END { if (config_added != 1 || manage_added != 1) exit 9 }
    ' "${candidate}" > "${candidate}.next"
    mv "${candidate}.next" "${candidate}"
fi

if grep -Fq "${old_redirect}" "${candidate}"; then
    echo "Refusing to install: HTTP-to-HTTPS redirect is still present." >&2
    exit 1
fi
if ! grep -Fq 'listen 80;' "${candidate}" || ! grep -Fq 'listen [::]:80;' "${candidate}"; then
    echo "Refusing to install: HTTP listeners are missing." >&2
    exit 1
fi
if ! grep -Fq "${new_backend}" "${candidate}"; then
    echo "Refusing to install: protocol-aware MetaCubeXD backend is missing." >&2
    exit 1
fi
if ! grep -Fq "${new_manage_redirect}" "${candidate}"; then
    echo "Refusing to install: /manage/ temporary redirect is missing." >&2
    exit 1
fi
if ! grep -Fq "${manage_auth_handler}" "${candidate}" || [[ "$(grep -Fc "${manage_auth_error}" "${candidate}" || true)" -ne 2 ]]; then
    echo "Refusing to install: /manage/ does not have an isolated Basic-auth challenge." >&2
    exit 1
fi

cp --preserve=mode,ownership,timestamps "${CONF_PATH}" "${backup}"
install -m 0644 -o root -g root "${candidate}" "${CONF_PATH}"

if ! "${NGINX_BIN}" -t; then
    cp --preserve=mode,ownership,timestamps "${backup}" "${CONF_PATH}"
    "${NGINX_BIN}" -t || true
    echo "Nginx validation failed; restored ${backup}." >&2
    exit 1
fi

if ! "${NGINX_BIN}" -s reload; then
    cp --preserve=mode,ownership,timestamps "${backup}" "${CONF_PATH}"
    "${NGINX_BIN}" -t || true
    echo "Nginx reload failed; restored ${backup}." >&2
    exit 1
fi

echo "Applied Nginx HTTP/manage fix. Backup: ${backup}"
