#!/data/data/com.termux/files/usr/bin/bash
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
APP="$ROOT/app"
BUILD="$ROOT/build"
AAPT_ANDROID_JAR="${AAPT_ANDROID_JAR:-$ROOT/build-tools/android-sdk/android-9/android.jar}"
JAVAC_ANDROID_JAR="${JAVAC_ANDROID_JAR:-$ROOT/build-tools/android-sdk/android-9/android.jar}"
R8_JAR="$ROOT/build-tools/r8.jar"
PKG="com.resonantsystems.hermesos"
VERSION_NAME="0.4.2"
VERSION_CODE="7"
TARGET_SDK="28"

rm -rf "$BUILD"
mkdir -p "$BUILD"/compiled "$BUILD"/gen "$BUILD"/classes "$BUILD"/dex "$BUILD"/outputs

# Keep bundled dashboard fresh from the hermes-os dist output if this script is run from the parent repo.
PARENT="$(cd "$ROOT/.." && pwd)"
if [ -f "$PARENT/dist/index.html" ]; then
  mkdir -p "$APP/src/main/assets"
  cp "$PARENT/dist/index.html" "$APP/src/main/assets/index.html"
fi
if [ -f "$PARENT/dist/llm-wiki-graph.html" ]; then
  mkdir -p "$APP/src/main/assets"
  cp "$PARENT/dist/llm-wiki-graph.html" "$APP/src/main/assets/llm-wiki-graph.html"
fi

if [ ! -f "$AAPT_ANDROID_JAR" ]; then
  echo "missing aapt include framework: $AAPT_ANDROID_JAR" >&2
  exit 1
fi
if [ ! -f "$JAVAC_ANDROID_JAR" ]; then
  echo "missing Android Java classes jar: $JAVAC_ANDROID_JAR" >&2
  exit 1
fi
if [ ! -f "$R8_JAR" ]; then
  echo "missing r8.jar: $R8_JAR" >&2
  exit 1
fi

# Package manifest, resources, and bundled HTML assets.
aapt2 compile --dir "$APP/src/main/res" -o "$BUILD/compiled/resources.zip"
aapt2 link \
  -o "$BUILD/unsigned-res.apk" \
  -I "$AAPT_ANDROID_JAR" \
  --manifest "$APP/src/main/AndroidManifest.xml" \
  -R "$BUILD/compiled/resources.zip" \
  -A "$APP/src/main/assets" \
  --java "$BUILD/gen" \
  --min-sdk-version 26 \
  --target-sdk-version "$TARGET_SDK" \
  --version-code "$VERSION_CODE" \
  --version-name "$VERSION_NAME" \
  --auto-add-overlay

# Compile Java sources plus generated R.java.
find "$APP/src/main/java" "$BUILD/gen" -name '*.java' > "$BUILD/sources.list"
javac -source 11 -target 11 \
  -classpath "$JAVAC_ANDROID_JAR" \
  -d "$BUILD/classes" \
  @"$BUILD/sources.list"

# Convert JVM classes to classes.dex.
( cd "$BUILD/classes" && jar cf "$BUILD/classes.jar" . )
java -cp "$R8_JAR" com.android.tools.r8.D8 \
  --lib "$JAVAC_ANDROID_JAR" \
  --output "$BUILD/dex" \
  "$BUILD/classes.jar"

cp "$BUILD/unsigned-res.apk" "$BUILD/unsigned.apk"
( cd "$BUILD/dex" && jar uf "$BUILD/unsigned.apk" classes.dex )

zipalign -f -p 4 "$BUILD/unsigned.apk" "$BUILD/outputs/hermes-os-unsigned-aligned.apk"

KS="$ROOT/hermes-os-debug.keystore"
if [ ! -f "$KS" ]; then
  keytool -genkeypair -v \
    -keystore "$KS" \
    -storepass android \
    -keypass android \
    -alias hermesos \
    -keyalg RSA \
    -keysize 2048 \
    -validity 10000 \
    -dname "CN=Hermes OS Debug,O=Resonant Systems,C=BR" >/dev/null
fi

apksigner sign \
  --ks "$KS" \
  --ks-key-alias hermesos \
  --ks-pass pass:android \
  --key-pass pass:android \
  --out "$BUILD/outputs/hermes-os-debug.apk" \
  "$BUILD/outputs/hermes-os-unsigned-aligned.apk"

apksigner verify --print-certs "$BUILD/outputs/hermes-os-debug.apk" >/dev/null
APK="$BUILD/outputs/hermes-os-debug.apk"
BYTES=$(wc -c < "$APK")
echo "built $APK ($BYTES bytes)"
