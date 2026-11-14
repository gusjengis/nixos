#include "DesktopTintMath.hpp"
#include <cassert>

int main() {
    using namespace DesktopTintMath;
    Payload p;
    p.width = p.height = p.stride = 8;
    p.integral.resize(64);
    for (int y = 0; y < 8; ++y) {
        RGBA row{};
        for (int x = 0; x < 8; ++x) {
            const RGBA pixel{x / 7.0f, y / 7.0f, (x + y) / 14.0f, 1};
            for (int c = 0; c < 4; ++c) {
                row[c] += pixel[c];
                p.integral[y * 8 + x][c] = row[c] + (y ? p.integral[(y - 1) * 8 + x][c] : 0);
            }
        }
    }
    // Native SkyLight output, not a second implementation of the formula.
    const auto a = p.average(1, 1, 4, 4);
    const RGBA expected{.3174603283405304f, .2698412835597992f, .2857142984867096f, .7619048357009888f};
    for (int i = 0; i < 4; ++i) assert(std::abs(a[i] - expected[i]) < 6e-8f);
    const auto fraction = p.average(.25f, .25f, 3.5f, 3.5f);
    assert(std::abs(fraction[3] - .7460317611694336f) < 6e-8f);
    const RGBA tones[] = {{0, 0, 0, 1}, {.5f, .5f, .5f, 1}, {1, 1, 1, 1}, {1, 0, 0, 1}, {0, 1, 0, 1}, {0, 0, 1, 1}};
    const RGB reference[] = {{27,27,27}, {40,40,40}, {53,53,53}, {51,32,31}, {39,53,35}, {27,27,52}};
    for (int i = 0; i < 6; ++i) {
        const auto actual = gamut(material(tones[i]), true);
        for (int c = 0; c < 3; ++c) assert(std::abs(std::floor(actual[c] * 255 + .5f) - reference[i][c]) <= 1);
    }
}
