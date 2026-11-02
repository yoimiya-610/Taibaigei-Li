#!/usr/bin/env bash
# Update the bot code with the smallest practical NoneBot interruption.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
BOT_DIR="$REPO_ROOT/mybot"

BRANCH="${BOT_BRANCH:-main}"
SERVICE_NAME="${BOT_SERVICE_NAME:-taibaigei.service}"
SYSTEMCTL_BIN="${BOT_SYSTEMCTL_BIN:-systemctl}"
START_WAIT="${BOT_START_WAIT:-3}"

runtime_state_dir=""
runtime_paths=()
recovery_required=false
startup_attempted=false

log() {
    printf '[deploy] %s\n' "$*"
}

fail() {
    printf '[deploy] error: %s\n' "$*" >&2
    return 1
}

require_command() {
    command -v "$1" >/dev/null 2>&1 || fail "required command not found: $1"
}

is_runtime_path() {
    case "$1" in
        mybot/data | mybot/data/* | mybot/logs | mybot/logs/* | backups | backups/*)
            return 0
            ;;
        *)
            return 1
            ;;
    esac
}

assert_no_local_code_changes() {
    local changed_path
    while IFS= read -r changed_path; do
        [[ -z "$changed_path" ]] && continue
        is_runtime_path "$changed_path" && continue
        fail "local tracked change found: $changed_path. Commit, stash, or revert it before deploying."
    done < <(
        {
            git -C "$REPO_ROOT" diff --name-only
            git -C "$REPO_ROOT" diff --cached --name-only
        } | sort -u
    )
}

service_active() {
    "$SYSTEMCTL_BIN" is-active --quiet "$SERVICE_NAME"
}

service_failed() {
    "$SYSTEMCTL_BIN" is-failed --quiet "$SERVICE_NAME"
}

service_main_pid() {
    "$SYSTEMCTL_BIN" show "$SERVICE_NAME" --property=MainPID --value
}

service_healthy() {
    local main_pid

    service_active || return 1
    main_pid="$(service_main_pid)" || return 1
    [[ "$main_pid" =~ ^[1-9][0-9]*$ ]] || return 1
    kill -0 "$main_pid" 2>/dev/null
}

print_service_diagnostics() {
    if service_failed; then
        printf '[deploy] error: systemd service %q is in failed state.\n' \
            "$SERVICE_NAME" >&2
    fi
    "$SYSTEMCTL_BIN" status "$SERVICE_NAME" --no-pager -l >&2 || true
    if command -v journalctl >/dev/null 2>&1; then
        journalctl -u "$SERVICE_NAME" -n 80 --no-pager >&2 || true
    fi
}

ensure_service_loaded() {
    local load_state

    load_state="$(
        "$SYSTEMCTL_BIN" show "$SERVICE_NAME" --property=LoadState --value
    )" || fail "cannot inspect systemd service '$SERVICE_NAME'."
    [[ "$load_state" == "loaded" ]] \
        || fail "systemd service '$SERVICE_NAME' is not loaded (state: ${load_state:-unknown})."
}

stop_bot() {
    if service_active; then
        log "stopping systemd service '$SERVICE_NAME'."
    else
        log "systemd service '$SERVICE_NAME' is not active; clearing any residual state."
    fi

    recovery_required=true
    "$SYSTEMCTL_BIN" stop "$SERVICE_NAME"

    if service_active; then
        fail "systemd service '$SERVICE_NAME' remained active after stop."
    fi
}

start_bot() {
    startup_attempted=true
    log "starting systemd service '$SERVICE_NAME'."

    if ! "$SYSTEMCTL_BIN" start "$SERVICE_NAME"; then
        print_service_diagnostics
        return 1
    fi

    sleep "$START_WAIT"
    if ! service_healthy; then
        printf '[deploy] error: systemd service %q did not become healthy after %ss.\n' \
            "$SERVICE_NAME" "$START_WAIT" >&2
        print_service_diagnostics
        return 1
    fi

    log "systemd service '$SERVICE_NAME' is active with MainPID $(service_main_pid)."
}

move_runtime_state_if_needed() {
    local path
    local current_files
    local incoming_files

    for path in mybot/data mybot/logs backups; do
        current_files="$(git -C "$REPO_ROOT" ls-tree -r --name-only HEAD -- "$path" | sed -n '1p')"
        incoming_files="$(git -C "$REPO_ROOT" ls-tree -r --name-only FETCH_HEAD -- "$path" | sed -n '1p')"

        if [[ -n "$current_files" && -z "$incoming_files" && -d "$REPO_ROOT/$path" ]]; then
            if [[ -z "$runtime_state_dir" ]]; then
                runtime_state_dir="${RUNTIME_STATE_ROOT:-$HOME}/taibaigei_runtime_state_$(date +%Y%m%d_%H%M%S)_$$"
                mkdir -p "$runtime_state_dir"
                log "incoming update stops tracking runtime state; preserving it in $runtime_state_dir."
            fi

            mkdir -p "$(dirname -- "$runtime_state_dir/$path")"
            mv "$REPO_ROOT/$path" "$runtime_state_dir/$path"
            runtime_paths+=("$path")
        fi
    done
}

restore_runtime_state() {
    local path
    for path in "${runtime_paths[@]}"; do
        [[ -e "$runtime_state_dir/$path" ]] || continue

        if [[ -e "$REPO_ROOT/$path" ]]; then
            log "runtime state remains at $runtime_state_dir/$path because $REPO_ROOT/$path already exists."
            continue
        fi

        mkdir -p "$(dirname -- "$REPO_ROOT/$path")"
        mv "$runtime_state_dir/$path" "$REPO_ROOT/$path"
    done
}

on_error() {
    local exit_code=$?
    trap - ERR
    set +e

    if [[ -n "$runtime_state_dir" ]]; then
        log "deployment failed; restoring preserved runtime state."
        restore_runtime_state || true
    fi

    if $recovery_required && ! service_healthy; then
        if $startup_attempted; then
            log "service startup failed; no second instance was started."
            log "systemd remains responsible for the configured restart policy."
        else
            log "deployment failed after the service was stopped; attempting automatic recovery."
            if start_bot; then
                log "automatic service recovery succeeded; deployment changes may still be incomplete."
            else
                log "automatic service recovery failed; inspect '$SERVICE_NAME' before retrying."
            fi
        fi
    fi

    exit "$exit_code"
}

trap on_error ERR

require_command git
require_command uv
require_command "$SYSTEMCTL_BIN"

git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "not a Git repository: $REPO_ROOT"
[[ -f "$BOT_DIR/bot.py" ]] || fail "bot entry point not found: $BOT_DIR/bot.py"

assert_no_local_code_changes
ensure_service_loaded

log "fetching origin/$BRANCH while the current bot stays online."
git -C "$REPO_ROOT" fetch --prune origin "$BRANCH"

current_commit="$(git -C "$REPO_ROOT" rev-parse HEAD)"
incoming_commit="$(git -C "$REPO_ROOT" rev-parse FETCH_HEAD)"

if [[ "$current_commit" == "$incoming_commit" ]]; then
    if service_healthy; then
        log "already at the latest origin/$BRANCH; service is healthy, no restart needed."
        exit 0
    fi

    log "already at the latest origin/$BRANCH, but the service is not healthy."
    stop_bot
    log "synchronizing locked Python dependencies before service recovery."
    uv sync --project "$BOT_DIR" --locked
    start_bot
    recovery_required=false
    log "service recovery complete. NapCat was not restarted."
    exit 0
fi

git -C "$REPO_ROOT" merge-base --is-ancestor "$current_commit" "$incoming_commit" \
    || fail "local branch cannot fast-forward to origin/$BRANCH; resolve the Git history manually."

stop_bot
move_runtime_state_if_needed

log "fast-forwarding to ${incoming_commit:0:12}."
git -C "$REPO_ROOT" merge --ff-only "$incoming_commit"

log "synchronizing locked Python dependencies."
uv sync --project "$BOT_DIR" --locked

restore_runtime_state

start_bot
recovery_required=false

log "update complete. NapCat was not restarted."
