#version 440

layout(location = 0) in vec2 qt_TexCoord0;
layout(location = 0) out vec4 fragColor;

layout(std140, binding = 0) uniform buf {
    mat4 qt_Matrix;
    float qt_Opacity;
    float darkContent;
    float stripHeight;
};

layout(binding = 1) uniform sampler2D source;

float toLinear(float value) {
    return value <= 0.04045 ? value / 12.92 : pow((value + 0.055) / 1.055, 2.4);
}

float toSrgb(float value) {
    return value <= 0.0031308 ? value * 12.92 : 1.055 * pow(value, 1.0 / 2.4) - 0.055;
}

void main() {
    vec3 wallpaper = texture(source, qt_TexCoord0).rgb;
    float luma = dot(wallpaper, vec3(0.2126, 0.7152, 0.0722));
    float linear = toLinear(luma);
    float blackAlpha = linear <= 0.150 ? 0.0 : 0.570 * (1.0 - exp(-(linear - 0.150) / 0.124));
    float darken = luma - toSrgb(linear * (1.0 - blackAlpha));
    float lift = max(0.0, 0.73013 * luma * luma * luma - 1.02637 * luma * luma - 0.15459 * luma + 0.44948);

    // Mac's underbelly is flat for about 20px and vanishes at about 172px.
    float t = clamp((qt_TexCoord0.y * stripHeight - 1.0) / 190.0, 0.0, 1.0);
    float fade = 1.0 - t * t * t * (t * (6.0 * t - 15.0) + 10.0);
    vec3 result = clamp(wallpaper + (darkContent > 0.5 ? lift : -darken) * fade, 0.0, 1.0);
    fragColor = vec4(result, 1.0) * qt_Opacity;
}
