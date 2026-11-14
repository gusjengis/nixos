// Included inside AppleGlass, sharing its work-buffer color conversion.
namespace {
    struct DesktopSample {
        GLuint texture = 0, framebuffer = 0;
        int width = 0, height = 0;
        std::vector<uint8_t> bytes;
        DesktopTintMath::Payload payload;
        ~DesktopSample() {
            if (texture) glDeleteTextures(1, &texture);
            if (framebuffer) glDeleteFramebuffers(1, &framebuffer);
        }
    };
    std::unordered_map<MONITORID, std::unique_ptr<DesktopSample>> desktopSamples;
    SP<CShader> desktopCopy;

    void captureDesktop(PHLMONITOR monitor) {
        const auto source = g_pHyprRenderer->m_renderData.currentFB;
        if (!source || !monitor) return;
        auto& entry = desktopSamples[monitor->m_id];
        if (!entry) entry = std::make_unique<DesktopSample>();
        auto& sample = *entry;
        // A partially repainted work buffer can contain foreground remnants
        // outside its damage. Never average those into the desktop.
        const CBox whole{0, 0, source->m_size.x, source->m_size.y};
        if (!CRegion(whole).subtract(g_pHyprRenderer->m_renderData.damage).empty()) {
            if (sample.payload.integral.empty()) g_pHyprRenderer->damageMonitor(monitor);
            return;
        }
        if (!desktopCopy) {
            desktopCopy = makeShared<CShader>();
            std::string code = SHADERS.at("applecopy.frag");
            code.insert(code.find("uniform vec2 srcSize"), "uniform vec2 dstSize;\n");
            const auto position = code.find("dstOrigin + gl_FragCoord.xy");
            code.replace(position, std::string("dstOrigin + gl_FragCoord.xy").size(), "gl_FragCoord.xy * srcSize / dstSize");
            if (!desktopCopy->createProgram(g_pHyprOpenGL->m_shaders->TEXVERTSRC, code, true)) {
                desktopCopy.reset();
                return;
            }
        }
        const int width = std::max(1, static_cast<int>(std::ceil(source->m_size.x / monitor->m_scale * .125)));
        const int height = std::max(1, static_cast<int>(std::ceil(source->m_size.y / monitor->m_scale * .125)));
        if (!sample.texture) {
            glGenTextures(1, &sample.texture);
            glGenFramebuffers(1, &sample.framebuffer);
        }
        glActiveTexture(GL_TEXTURE0);
        glBindTexture(GL_TEXTURE_2D, sample.texture);
        if (sample.width != width || sample.height != height) {
            glTexImage2D(GL_TEXTURE_2D, 0, GL_RGBA8, width, height, 0, GL_RGBA, GL_UNSIGNED_BYTE, nullptr);
            sample.width = width; sample.height = height;
        }
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MIN_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_MAG_FILTER, GL_LINEAR);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_S, GL_CLAMP_TO_EDGE);
        glTexParameteri(GL_TEXTURE_2D, GL_TEXTURE_WRAP_T, GL_CLAMP_TO_EDGE);
        glBindFramebuffer(GL_FRAMEBUFFER, sample.framebuffer);
        glFramebufferTexture2D(GL_FRAMEBUFFER, GL_COLOR_ATTACHMENT0, GL_TEXTURE_2D, sample.texture, 0);
        if (glCheckFramebufferStatus(GL_FRAMEBUFFER) != GL_FRAMEBUFFER_COMPLETE) {
            glBindFramebuffer(GL_FRAMEBUFFER, fbId(source));
            return;
        }
        glDisable(GL_SCISSOR_TEST);
        glDisable(GL_STENCIL_TEST);
        g_pHyprRenderer->blend(false);
        g_pHyprOpenGL->setViewport(0, 0, width, height);
        auto shader = g_pHyprOpenGL->useShader(desktopCopy);
        shader->setUniformMatrix3fv(SHADER_PROJ, 1, GL_FALSE, FULLSCREEN_PROJECTION);
        shader->setUniformInt(SHADER_TEX, 0);
        const auto program = shader->program();
        glUniform2f(glGetUniformLocation(program, "srcSize"), source->m_size.x, source->m_size.y);
        glUniform2f(glGetUniformLocation(program, "dstSize"), width, height);
        glUniform1i(glGetUniformLocation(program, "bodyFill"), 0);
        uploadWork(program, workSpace(monitor));
        source->getTexture()->bind();
        glBindVertexArray(shader->getUniformLocation(SHADER_SHADER_VAO));
        glDrawArrays(GL_TRIANGLE_STRIP, 0, 4);
        glBindVertexArray(0);
        std::vector<uint8_t> bytes(width * height * 4);
        GLint packBuffer = 0;
        glGetIntegerv(GL_PIXEL_PACK_BUFFER_BINDING, &packBuffer);
        glBindBuffer(GL_PIXEL_PACK_BUFFER, 0);
        glReadPixels(0, 0, width, height, GL_RGBA, GL_UNSIGNED_BYTE, bytes.data());
        glBindBuffer(GL_PIXEL_PACK_BUFFER, packBuffer);
        if (bytes != sample.bytes) {
            sample.payload.assign(bytes, width, height);
            sample.bytes = std::move(bytes);
        }
        glBindTexture(GL_TEXTURE_2D, 0);
        glBindFramebuffer(GL_FRAMEBUFFER, fbId(source));
        g_pHyprOpenGL->setViewport(0, 0, source->m_size.x, source->m_size.y);
        g_pHyprRenderer->blend(true);
    }

    class CDesktopSamplePass : public IPassElement {
        PHLMONITORREF monitor;
      public:
        explicit CDesktopSamplePass(PHLMONITORREF m) : monitor(m) {}
        std::vector<UP<IPassElement>> draw() override { captureDesktop(monitor.lock()); return {}; }
        bool needsLiveBlur() override { return true; }
        bool needsPrecomputeBlur() override { return false; }
        bool disableSimplification() override { return true; }
        std::optional<CBox> boundingBox() override {
            if (const auto m = monitor.lock())
                return CBox{0, 0, m->m_transformedSize.x / m->m_scale, m->m_transformedSize.y / m->m_scale};
            return CBox{};
        }
        const char* passName() override { return "CDesktopAffinityCapture"; }
        ePassElementType type() override { return EK_CUSTOM; }
    };
}

void queueDesktopCapture() {
    if (g_pHyprRenderer->m_bRenderingSnapshot || RenderGuards::isForeignRender()) return;
    g_pHyprRenderer->m_renderPass.add(makeUnique<CDesktopSamplePass>(g_pHyprRenderer->m_renderData.pMonitor));
}

void clearDesktopSamples() {
    desktopSamples.clear();
    if (desktopCopy) desktopCopy->destroy();
    desktopCopy.reset();
}

SParams desktopParams(std::string_view name, SParams params, PHLMONITOR monitor, const std::optional<CBox>& windowBox) {
    if (!monitor || !windowBox) return params;
    const auto found = desktopSamples.find(monitor->m_id);
    if (found == desktopSamples.end()) return params;
    const auto& payload = found->second->payload;
    const auto& box = *windowBox;
    const float sx = .125f / monitor->m_scale, sy = sx;
    const auto tone = payload.average(box.x * sx, box.y * sy, box.w * sx, box.h * sy);
    const auto surface = DesktopTintMath::material(tone);
    if (params.bodyFill) params.bodyColor = surface;
    if (name == "apple-toolbar-base" || name == "apple-content" || name == "apple-footer" || name == "apple-sidebar-inactive" || name == "apple-card" || name == "apple-card-hover") {
        auto base = DesktopTintMath::RGB{DesktopTintMath::FILL, DesktopTintMath::FILL, DesktopTintMath::FILL};
        if (name == "apple-footer") base = {48.0f / 255, 48.0f / 255, 48.0f / 255};
        if (name == "apple-sidebar-inactive") base = {44.0f / 255, 45.0f / 255, 46.0f / 255};
        if (name == "apple-card") base = {54.0f / 255, 54.0f / 255, 57.0f / 255};
        if (name == "apple-card-hover") base = {69.0f / 255, 69.0f / 255, 72.0f / 255};
        const auto color = DesktopTintMath::material(tone, base);
        params.faceCm = {Row{0, 0, 0, color[0]}, Row{0, 0, 0, color[1]}, Row{0, 0, 0, color[2]}};
    }
    return params;
}

void drawNeutralCards(PHLMONITOR monitor, const SNeutralCards& cards, const CBox& rawBox, float inset, float alpha) {
    if (!monitor || !cards.count) return;
    const float scale = monitor->m_scale;
    const CBox body{rawBox.x + inset * scale, rawBox.y + inset * scale,
        rawBox.w - 2 * inset * scale, rawBox.h - 2 * inset * scale};
    const auto sampleBox = WindowGeometry::applyMonitorTransform(body, monitor);
    auto clip = body;
    if (cards.clip) {
        const auto& c = *cards.clip;
        clip = CBox{body.x + c.x * scale, body.y + c.y * scale, c.width * scale, c.height * scale}.intersection(body);
    }
    const auto damage = g_pHyprRenderer->m_renderData.damage.copy().intersect(WindowGeometry::applyMonitorTransform(clip, monitor));
    if (damage.empty()) return;
    for (int i = 0; i < cards.count; ++i) {
        const auto& r = cards.rects[i];
        if (r.width <= 0 || r.height <= 0) continue;
        const CBox box{body.x + r.x * scale, body.y + r.y * scale, r.width * scale, r.height * scale};
        const auto params = desktopParams(cards.hovered[i] ? "apple-card-hover" : "apple-card", makeToolbarBase(), monitor, sampleBox);
        const CHyprColor color{params.faceCm[0][3], params.faceCm[1][3], params.faceCm[2][3], alpha};
        g_pHyprOpenGL->renderRect(box, color, {.damage = &damage, .round = static_cast<int>(std::round(r.radius * scale))});
    }
}
