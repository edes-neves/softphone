# Empacotamento VoiceNeves

- `debian/` - arquivos para build .deb (fpm/dpkg)
- `flatpak/` - manifest flatpak (`com.edesneves.VoiceNeves.yml`)
- scripts em raiz podem ser usados localmente

## Repositório Flatpak (GitHub Pages)

O workflow `.github/workflows/release.yml` gera, a cada tag `v*`, um **repositório
Flatpak** (OSTree) assinado com GPG e o publica no GitHub Pages, junto dos arquivos
`voiceneves.flatpakrepo` e `com.edesneves.VoiceNeves.flatpakref`. O cliente
(`flatpak`/GNOME Software/KDE Discover) exige **assinatura de commit e de sumário**,
por isso o build usa `flatpak-builder --gpg-sign` e `flatpak build-update-repo --gpg-sign`.

A chave privada de assinatura fica no secret **`FLATPAK_GPG_PRIVATE_KEY`**
(fingerprint `B5E44D30744036013ED6482F73D7029769729D73`). Sem o secret, o build segue,
mas o repo sai sem assinatura (não instala com verificação GPG).

Instruções de instalação para o usuário final: ver a seção
*Downloads e instalação → Flatpak via repositório* no `README.md` da raiz.
