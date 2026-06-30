#!/usr/bin/env bash
# Update the bot code with the smallest practical NoneBot interruption.
set -Eeuo pipefail

SCRIPT_DIR="$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)"
REPO_ROOT="$(cd -- "$SCRIPT_DIR/.." && pwd)"
BOT_DIR="$REPO_ROOT/mybot"

BRANCH="${BOT_BRANCH:-main}"
SCREEN_NAME="${BOT_SCREEN_NAME:-nonebot}"
STOP_TIMEOUT="${BOT_STOP_TIMEOUT:-20}"
START_WAIT="${BOT_START_WAIT:-3}"

runtime_state_dir=""
runtime_paths=()
bot_was_running=false
bot_stopped=false
bot_started=false

log() {
    printf '[deploy] %s\n' "$*"
}

fail() {
    printf '[deploy] error: %s\n' "$*" >&2
    exit 1
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

screen_session_active() {
    screen -list 2>/dev/null | grep -Eq "[[:space:]][0-9]+\\.${SCREEN_NAME}[[:space:]]"
}

stop_bot() {
    if ! screen_session_active; then
        log "no active Screen session named '$SCREEN_NAME'; continuing."
        return
    fi

    bot_was_running=true
    log "stopping bot Screen session '$SCREEN_NAME'."
    screen -S "$SCREEN_NAME" -p 0 -X stuff $'\003'

    local deadline=$((SECONDS + STOP_TIMEOUT))
    while screen_session_active && (( SECONDS < deadline )); do
        sleep 1
    done

    if screen_session_active; then
        log "bot did not exit within ${STOP_TIMEOUT}s; closing its Screen session."
        screen -S "$SCREEN_NAME" -X quit
    fi

    bot_stopped=true
    screen -wipe >/dev/null 2>&1 || true
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
                runtime_state_dir="${RUNTIME_STATE_ROOT:-$HOME}/qqbot_runtime_state_$(date +%Y%m%d_%H%M%S)_$$"
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

    if [[ -n "$runtime_state_dir" ]]; then
        log "deployment failed; restoring preserved runtime state."
        restore_runtime_state || true
    fi

    if $bot_was_running && $bot_stopped && ! $bot_started; then
        log "the bot remains stopped; resolve the error, then run this script again."
    fi

    exit "$exit_code"
}

trap on_error ERR

require_command git
require_command screen
require_command uv

git -C "$REPO_ROOT" rev-parse --is-inside-work-tree >/dev/null 2>&1 || fail "not a Git repository: $REPO_ROOT"
[[ -f "$BOT_DIR/bot.py" ]] || fail "bot entry point not found: $BOT_DIR/bot.py"

assert_no_local_code_changes

log "fetching origin/$BRANCH while the current bot stays online."
git -C "$REPO_ROOT" fetch --prune origin "$BRANCH"

current_commit="$(git -C "$REPO_ROOT" rev-parse HEAD)"
incoming_commit="$(git -C "$REPO_ROOT" rev-parse FETCH_HEAD)"

if [[ "$current_commit" == "$incoming_commit" ]]; then
    log "already at the latest origin/$BRANCH; no restart needed."
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

log "starting bot Screen session '$SCREEN_NAME'."
screen -dmS "$SCREEN_NAME" bash -lc "export PYTHONIOENCODING=utf-8; cd $(printf '%q' "$BOT_DIR") && exec uv run python bot.py"
bot_started=true

sleep "$START_WAIT"
if ! screen_session_active; then
    fail "bot exited during startup; inspect its logs before retrying."
fi

log "update complete. NapCat was not restarted."
