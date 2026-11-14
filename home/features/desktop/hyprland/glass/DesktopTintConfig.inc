static SNeutralCards readNeutralCards(lua_State* L) {
    SNeutralCards result;
    lua_getfield(L, 2, "mac_neutral_rects");
    if (!lua_isnil(L, -1)) {
        if (!lua_istable(L, -1)) luaL_error(L, "mac_neutral_rects must be an array");
        const auto count = lua_rawlen(L, -1);
        if (count > result.rects.size()) luaL_error(L, "too many neutral rectangles");
        result.count = count;
        constexpr const char* keys[] = {"x", "y", "width", "height", "radius"};
        for (size_t i = 0; i < count; ++i) {
            lua_rawgeti(L, -1, i + 1);
            if (!lua_istable(L, -1)) luaL_error(L, "neutral rectangle must be a table");
            float values[5]{};
            for (int j = 0; j < 5; ++j) {
                lua_getfield(L, -1, keys[j]);
                if (!lua_isnumber(L, -1)) luaL_error(L, "neutral rectangle fields must be numbers");
                values[j] = lua_tonumber(L, -1);
                if (!std::isfinite(values[j]) || std::abs(values[j]) > 1000000 || (j >= 2 && values[j] < 0))
                    luaL_error(L, "invalid neutral rectangle");
                lua_pop(L, 1);
            }
            result.rects[i] = {values[0], values[1], values[2], values[3], values[4]};
            lua_getfield(L, -1, "hovered");
            result.hovered[i] = lua_toboolean(L, -1);
            lua_pop(L, 2);
        }
    }
    lua_pop(L, 1);
    lua_getfield(L, 2, "mac_neutral_clip");
    if (!lua_isnil(L, -1)) {
        if (!lua_istable(L, -1)) luaL_error(L, "mac_neutral_clip must be a table");
        constexpr const char* keys[] = {"x", "y", "width", "height"};
        float values[4]{};
        for (int j = 0; j < 4; ++j) {
            lua_getfield(L, -1, keys[j]);
            if (!lua_isnumber(L, -1)) luaL_error(L, "neutral clip fields must be numbers");
            values[j] = lua_tonumber(L, -1);
            if (!std::isfinite(values[j]) || std::abs(values[j]) > 1000000 || (j >= 2 && values[j] < 0))
                luaL_error(L, "invalid neutral clip");
            lua_pop(L, 1);
        }
        result.clip = SMacRect{values[0], values[1], values[2], values[3], 0};
    }
    lua_pop(L, 1);
    return result;
}
