#!/usr/bin/env bash
# bump.sh — Padroniza o lançamento de uma versão do Voice Neves.
#
# Faz o bump de versão em voice_neves/__init__.py, commita e cria/envia a tag
# v<versão> que dispara o release.yml (AppImage + version.json) no GitHub.
#
# Uso:
#   ./bump.sh 1.1.1                # bump + commit + tag + push
#   ./bump.sh 1.1.1 --date 09/2026 # atualiza também a data exibida na UI
#   ./bump.sh 1.1.1 --dry-run      # mostra o que faria, sem alterar nada
#
# Regra: a tag SEMPRE deve bater com __version__; o release.yml deriva dela.
set -Eeuo pipefail

cd "$(dirname "$0")"

INIT="voice_neves/__init__.py"
CONSTANTS="voice_neves/constants.py"
DRY_RUN=0
UPDATE_DATE=""

log() { printf '\033[1;34m[bump]\033[0m %s\n' "$*"; }
warn() { printf '\033[1;33m[bump][aviso]\033[0m %s\n' "$*" >&2; }
err() { printf '\033[1;31m[bump][ERRO]\033[0m %s\n' "$*" >&2; exit 1; }

# ---- 0. Argumentos -----------------------------------------------------------
NEW_VERSION="${1:-}"
[[ -n "$NEW_VERSION" ]] || err "informe a nova versão: ./bump.sh <versão> [--date MM/AAAA] [--dry-run]"
shift

while [[ $# -gt 0 ]]; do
  case "$1" in
    --date)
      UPDATE_DATE="${2:-}"
      [[ -n "$UPDATE_DATE" ]] || err "--date exige um valor (ex.: 09/2026)"
      shift 2
      ;;
    --dry-run)
      DRY_RUN=1
      shift
      ;;
    *)
      err "argumento desconhecido: $1"
      ;;
  esac
done

# ---- 1. Validações -----------------------------------------------------------
[[ "$NEW_VERSION" =~ ^[0-9]+\.[0-9]+\.[0-9]+$ ]] \
  || err "versão inválida '$NEW_VERSION' (use SemVer: X.Y.Z, ex.: 1.1.1)"

if (( DRY_RUN )); then
  log "MODO DRY-RUN: nenhuma alteração será feita."
fi

# Versão atual lida de voice_neves/__init__.py (fonte da verdade do build)
CUR_VERSION="$(sed -n 's/^__version__ = "\(.*\)"/\1/p' "$INIT" | tr -d '[:space:]')"
[[ -n "$CUR_VERSION" ]] || err "não consegui ler a versão atual em $INIT"

# Chevron-release / semver desc: valida se a nova é maior que a atual
if [[ "$(printf '%s\n%s\n' "$NEW_VERSION" "$CUR_VERSION" | sort -V | tail -1)" != "$NEW_VERSION" ]]; then
  err "nova versão '$NEW_VERSION' não é maior que a atual '$CUR_VERSION'"
fi

TAG="v$NEW_VERSION"
if git rev-parse --verify "refs/tags/$TAG" >/dev/null 2>&1; then
  err "a tag $TAG já existe no repositório local"
fi

# Branch deve ser master (padrão que o release.yml atualiza)
BRANCH="$(git branch --show-current)"
[[ "$BRANCH" == "master" ]] || warn "você está no branch '$BRANCH' (o release.yml commita em master)"

if (( ! DRY_RUN )); then
  git diff --quiet && git diff --cached --quiet \
    || err "working tree tem alterações não commitadas; faça o commit antes de rodar o bump"
fi

# ---- 2. Resumo ---------------------------------------------------------------
log "Versão atual : $CUR_VERSION"
log "Nova versão  : $NEW_VERSION"
log "Tag          : $TAG"
[[ -n "$UPDATE_DATE" ]] && log "Data UI      : $UPDATE_DATE"

# ---- 3. Atualiza os arquivos ------------------------------------------------
run() {
  if (( DRY_RUN )); then
    log "  (dry-run) $*"
  else
    "$@"
  fi
}

if (( ! DRY_RUN )); then
  sed -i "s|^__version__ = \".*\"|__version__ = \"$NEW_VERSION\"|" "$INIT"
  if [[ -n "$UPDATE_DATE" ]]; then
    sed -i "s|^APP_UPDATED = \".*\"|APP_UPDATED = \"$UPDATE_DATE\"|" "$CONSTANTS"
  fi
  run git add "$INIT"
  [[ -n "$UPDATE_DATE" ]] && run git add "$CONSTANTS"
  run git commit -m "Bump da versao para $NEW_VERSION"
  run git tag "$TAG"
  run git push origin master
  run git push origin "$TAG"
  log "Pronto. O GitHub Actions vai gerar AppImage + version.json para $TAG"
else
  sed -n 's|^__version__ = "\(.*\)"|    __version__: "\1" -> "'"$NEW_VERSION"'"|p' "$INIT"
  [[ -n "$UPDATE_DATE" ]] && sed -n 's|^APP_UPDATED = "\(.*\)"|    APP_UPDATED:  "\1" -> "'"$UPDATE_DATE"'"|p' "$CONSTANTS"
  log "Comandos que seriam executados:"
  log "  git add $INIT $([[ -n "$UPDATE_DATE" ]] && echo "$CONSTANTS")"
  log "  git commit -m 'Bump da versao para $NEW_VERSION'"
  log "  git tag $TAG"
  log "  git push origin master && git push origin $TAG"
fi
