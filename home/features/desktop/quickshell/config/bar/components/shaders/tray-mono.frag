#version 440

// Recolors a tray icon to monochrome so it follows the bar's black/white
// content color without flattening it into a silhouette.
//
// The icon is converted to luminance and normalized so its brightest opaque
// pixel lands exactly on 1.0; everything else keeps its relative brightness.
// On dark wallpapers that normalized value is drawn as-is (brightest -> white).
// On bright wallpapers it is mirrored (brightest -> black), which keeps the
// same internal contrast the icon had in white mode. Alpha is untouched.

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    // 0 = white content (dark wallpaper), 1 = black content (bright wallpaper).
    float darkContent;
};

layout(binding = 1) uniform sampler2D source;

// Grid used to find the brightest pixel. Tray icons render around 20-40 px,
// so this touches (nearly) every texel while keeping the loop bound constant.
const int GRID = 32;
// Pixels fainter than this are anti-aliased edges and do not set the peak.
const float PEAK_ALPHA = 0.5;
// Below this peak the icon is effectively black; normalizing would only
// amplify noise, so it is drawn as a flat silhouette instead.
const float MIN_PEAK = 0.05;

float luminance(vec4 premultiplied) {
    vec3 rgb = premultiplied.rgb / max(premultiplied.a, 1e-4);
    return dot(rgb, vec3(0.2126, 0.7152, 0.0722));
}

void main() {
    float peak = 0.0;
    for (int y = 0; y < GRID; ++y) {
        for (int x = 0; x < GRID; ++x) {
            vec4 texel = texture(source, (vec2(x, y) + 0.5) / float(GRID));
            if (texel.a > PEAK_ALPHA)
                peak = max(peak, luminance(texel));
        }
    }

    vec4 pixel = texture(source, qt_TexCoord0);
    float normalized = peak < MIN_PEAK ? 1.0 : clamp(luminance(pixel) / peak, 0.0, 1.0);
    float value = mix(normalized, 1.0 - normalized, darkContent);
    fragColor = vec4(vec3(value) * pixel.a, pixel.a) * qt_Opacity;
}
