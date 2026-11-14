// macOS 27.0.1 (26A434), dark appearance, glass diffusion 1.
// Live ControlCenter / NotificationCenter CAFilter inputs and highlight matrices:
// MacOS Theme/27-real-glass/data/live-{cc,nc}-final.json.
// Filter inputs were replayed through Apple's CARenderer and its GPU uniforms
// decoded in renders/live/render.log. These are not screenshot-fitted profiles.
// Include inside AppleGlass's anonymous namespace, after makeDock/makeMenu.

SParams makeControlCenter() {
    auto p = makeDock();
    p.innerRefrAmount = -80.0f;
    p.innerRefrInvH = 0.06944f;
    p.outerRefrAmount = 9.996f;
    p.outerRefrInvH = 0.20008f;
    p.refrOpacity = 0.15247f;
    p.blurRadius = 3.2f;
    p.blurAlpha = {1.0f, 0.8999f, -0.3999f, -0.5f};
    p.blurDist = {-100.0f, -1.0f, 0.0f, 0.0f};
    p.faceCm = {Row{1.08887f, -0.37549f, -0.03781f, 0.125f},
                Row{-0.11163f, 0.82471f, -0.03793f, 0.125f},
                Row{-0.11169f, -0.37549f, 1.16211f, 0.125f}};
    p.lumaComplement = 0.0f;
    p.shadowInvH = 0.01786f;
    p.hlHeight = 0.5f;
    p.hlOffset = -0.5f;
    p.hlBias = -0.30005f;
    p.margin = 16.0f;
    p.ovalization = 1.0f;
    auto& h = p.highlightLayer;
    h.keySpread = h.fillSpread = 1.476257659f;
    h.cm = {Row{1.31919992f, -0.0478f, -0.0047f, 0.199999988f},
            Row{-0.0142f, 1.28559995f, -0.0048f, 0.199999988f},
            Row{-0.0142f, -0.0476f, 1.32849991f, 0.199999988f}};
    h.clamp = 1.200000048f;
    return p;
}

SParams makeNotification() {
    auto p = makeMenu();
    p.innerRefrAmount = -29.0f;
    p.innerRefrInvH = 0.06897f;
    p.outerRefrAmount = 16.0f;
    p.outerRefrInvH = 0.0625f;
    p.blurAlpha = {0.0f, 0.0f, -0.5f, -0.5f};
    p.blurDist = {-29.0f, -1.0f, 0.0f, 0.0f};
    p.lumaComplement = 0.4f;
    p.bleedAmount = 20.3f;
    p.bleedInvH = 0.04926f;
    p.bleedBlur = p.bleedOpacity = 0.0f;
    p.shadowInvRadius = 0.25f;
    p.shadowOpacity = 0.04001f;
    p.hlHeight = 0.5f;
    p.hlOffset = -0.5f;
    p.margin = 16.0f;
    p.ovalization = 0.1488f;
    auto& h = p.highlightLayer;
    h.keySpread = h.fillSpread = 1.396263402f;
    h.cm = {Row{1.12019992f, -0.1894f, -0.019f, 0.147100002f},
            Row{-0.0563f, 0.987099946f, -0.0191f, 0.147100002f},
            Row{-0.0563f, -0.1893f, 1.157400012f, 0.147100002f}};
    h.clamp = 1.200000048f;
    return p;
}
