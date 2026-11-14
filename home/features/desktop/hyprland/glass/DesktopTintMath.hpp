#pragma once
#include <algorithm>
#include <array>
#include <cmath>
#include <cstdint>
#include <vector>

// SkyLight Payload::average_color and the extracted encoded-P3 Chameleon
// source-over. Kept independent of GL/Hyprland for native-oracle fixtures.
namespace DesktopTintMath {
using RGBA = std::array<float, 4>;
using RGB = std::array<float, 3>;
constexpr float FILL = 0.11759999394416809f;
constexpr float OPACITY = 0.10000000149011612f;

struct Payload {
    int width = 0, height = 0, stride = 0;
    std::vector<RGBA> integral;

    void assign(const std::vector<uint8_t>& pixels, int w, int h) {
        width = w; height = h; stride = (w + 3) & ~3;
        integral.assign(stride * h, {});
        for (int y = 0; y < h; ++y) {
            RGBA row{};
            for (int x = 0; x < w; ++x)
                for (int c = 0; c < 4; ++c) {
                    row[c] += pixels[(y * w + x) * 4 + c] / 255.0f;
                    integral[y * stride + x][c] = row[c] + (y ? integral[(y - 1) * stride + x][c] : 0.0f);
                }
        }
    }

    RGBA average(float x, float y, float w, float h) const {
        const float rightEdge = std::clamp(x + w, 0.0f, static_cast<float>(width));
        const float bottomEdge = std::clamp(y + h, 0.0f, static_cast<float>(height));
        x = std::clamp(x, 0.0f, static_cast<float>(width));
        y = std::clamp(y, 0.0f, static_cast<float>(height));
        w = rightEdge - x; h = bottomEdge - y;
        if (w <= 0 || h <= 0 || integral.empty()) return {};
        const int left = static_cast<int>(x), top = static_cast<int>(y) - 1;
        const int right = left + static_cast<int>(w) - 1, bottom = top + static_cast<int>(h);
        const auto at = [&](int col, int row) -> RGBA {
            const int i = row * stride + col;
            return i >= 0 && i < static_cast<int>(integral.size()) ? integral[i] : RGBA{};
        };
        const auto a = left && top >= 0 ? at(left, top) : RGBA{};
        const auto b = top >= 0 ? at(right, top) : RGBA{};
        const auto c = left ? at(left, bottom) : RGBA{};
        const auto d = at(right, bottom);
        RGBA result{};
        for (int i = 0; i < 4; ++i) {
            const float mean = std::clamp(((a[i] + d[i]) - b[i] - c[i]) / (w * h), 0.0f, 1.0f);
            result[i] = std::min(std::floor(mean * 64.0f), 63.0f) * (1.0f / 63.0f);
        }
        return result;
    }
};

inline RGB gamut(RGB rgb, bool toP3) {
    constexpr double forward[3][3] = {{.822461969, .177538031, 0}, {.0331941989, .966805801, 0}, {.0170826307, .0723974407, .910519929}};
    constexpr double inverse[3][3] = {{1.224940176, -.224940176, 0}, {-.0420569547, 1.0420569547, 0}, {-.0196375546, -.0786360456, 1.0982736002}};
    const auto& matrix = toP3 ? forward : inverse;
    std::array<double, 3> linear{};
    for (int i = 0; i < 3; ++i)
        linear[i] = rgb[i] <= .04045 ? rgb[i] / 12.92 : std::pow((rgb[i] + .055) / 1.055, 2.4);
    RGB result{};
    for (int i = 0; i < 3; ++i) {
        const double c = matrix[i][0] * linear[0] + matrix[i][1] * linear[1] + matrix[i][2] * linear[2];
        result[i] = c <= .0031308 ? 12.92 * c : 1.055 * std::pow(c, 1.0 / 2.4) - .055;
    }
    return result;
}

inline RGB material(RGBA tone, RGB base = {FILL, FILL, FILL}) {
    if (tone[3] <= 0) return base;
    const RGB color = gamut({tone[0] / tone[3], tone[1] / tone[3], tone[2] / tone[3]}, true);
    RGB fill = gamut(base, true);
    for (int i = 0; i < 3; ++i) fill[i] = fill[i] * (1.0f - tone[3] * OPACITY) + color[i] * tone[3] * OPACITY;
    fill = gamut(fill, false);
    for (auto& c : fill) c = std::clamp(c, 0.0f, 1.0f);
    return fill;
}
}
