#!/usr/bin/env bash
# Собирает .vsix из исходников (zip + vsixmanifest).
set -euo pipefail
ROOT="$(cd "$(dirname "$0")" && pwd)"
cd "$ROOT"

VERSION="$(python3 -c "import json; print(json.load(open('package.json'))['version'])")"
NAME="$(python3 -c "import json; print(json.load(open('package.json'))['name'])")"
OUT="${NAME}-${VERSION}.vsix"
STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT

mkdir -p "$STAGE/extension/themes"
cp package.json readme.md "$STAGE/extension/"
cp themes/*.json "$STAGE/extension/themes/"
[[ -f "КАК-ВЫБРАТЬ.md" ]] && cp "КАК-ВЫБРАТЬ.md" "$STAGE/extension/"

cat > "$STAGE/extension.vsixmanifest" <<EOF
<?xml version="1.0" encoding="utf-8"?>
<PackageManifest Version="2.0.0" xmlns="http://schemas.microsoft.com/developer/vsx-schema/2011" xmlns:d="http://schemas.microsoft.com/developer/vsx-schema-design/2011">
  <Metadata>
    <Identity Language="en-US" Id="${NAME}" Version="${VERSION}" Publisher="aleksandr" />
    <DisplayName>Aleksandr Cursor Themes</DisplayName>
    <Description xml:space="preserve">Кастомные темы Cursor для Александра: Dark, Light, Night Gold, Beige</Description>
    <Tags>theme,color-theme</Tags>
    <Categories>Themes</Categories>
    <GalleryFlags>Public</GalleryFlags>
    <Properties>
      <Property Id="Microsoft.VisualStudio.Code.Engine" Value="^1.74.0" />
      <Property Id="Microsoft.VisualStudio.Code.ExtensionKind" Value="ui,workspace,web" />
      <Property Id="Microsoft.VisualStudio.Services.GitHubFlavoredMarkdown" Value="true" />
      <Property Id="Microsoft.VisualStudio.Services.Content.Pricing" Value="Free"/>
    </Properties>
  </Metadata>
  <Installation>
    <InstallationTarget Id="Microsoft.VisualStudio.Code"/>
  </Installation>
  <Dependencies/>
  <Assets>
    <Asset Type="Microsoft.VisualStudio.Code.Manifest" Path="extension/package.json" Addressable="true" />
    <Asset Type="Microsoft.VisualStudio.Services.Content.Details" Path="extension/readme.md" Addressable="true" />
  </Assets>
</PackageManifest>
EOF

cat > "$STAGE/[Content_Types].xml" <<'EOF'
<?xml version="1.0" encoding="utf-8"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="json" ContentType="application/json"/>
  <Default Extension="vsixmanifest" ContentType="text/xml"/>
  <Default Extension="md" ContentType="text/markdown"/>
  <Default Extension="xml" ContentType="text/xml"/>
</Types>
EOF

rm -f "$OUT"
(
  cd "$STAGE"
  zip -qr "$ROOT/$OUT" extension.vsixmanifest "[Content_Types].xml" extension
)

echo "Built: $ROOT/$OUT"
