// Capture resolved public AppKit appearance inputs without changing user settings.
// clang -fobjc-arc -framework AppKit extract-appkit-theme.m -o extract-appkit-theme
#import <AppKit/AppKit.h>
#import <objc/runtime.h>

static NSDictionary *Color(NSColor *color) {
  NSColor *rgb = [color colorUsingColorSpace:NSColorSpace.sRGBColorSpace];
  if (!rgb) return @{ @"unresolved": @"not representable in sRGB",
                      @"description": color.description };
  CGFloat r, g, b, a;
  [rgb getRed:&r green:&g blue:&b alpha:&a];
  return @{ @"srgb": @[@(r), @(g), @(b), @(a)],
            @"argb": [NSString stringWithFormat:@"%02X%02X%02X%02X",
              (unsigned)lround(fmax(0, fmin(1, a)) * 255),
              (unsigned)lround(fmax(0, fmin(1, r)) * 255),
              (unsigned)lround(fmax(0, fmin(1, g)) * 255),
              (unsigned)lround(fmax(0, fmin(1, b)) * 255)] };
}

static NSDictionary *Font(NSFont *font) {
  if (!font) return @{};
  return @{ @"postscriptName": font.fontName, @"family": font.familyName ?: @"",
            @"size": @(font.pointSize), @"ascender": @(font.ascender),
            @"descender": @(font.descender), @"leading": @(font.leading),
            @"capHeight": @(font.capHeight), @"xHeight": @(font.xHeight),
            @"traits": font.fontDescriptor.fontAttributes[NSFontTraitsAttribute] ?: @{} };
}

static NSArray *ColorSelectors(void) {
  NSMutableSet *names = [NSMutableSet set];
  for (Class cls = object_getClass(NSColor.class); cls; cls = class_getSuperclass(cls)) {
    unsigned count = 0;
    Method *methods = class_copyMethodList(cls, &count);
    for (unsigned i = 0; i < count; ++i) {
      NSString *name = NSStringFromSelector(method_getName(methods[i]));
      // Public semantic color getters, including getters added by newer macOS.
      if (![name hasPrefix:@"_"] && [name hasSuffix:@"Color"] &&
          method_getNumberOfArguments(methods[i]) == 2) {
        char *type = method_copyReturnType(methods[i]);
        if (type[0] == '@') [names addObject:name];
        free(type);
      }
    }
    free(methods);
  }
  return [names.allObjects sortedArrayUsingSelector:@selector(compare:)];
}

int main(void) {
  @autoreleasepool {
    [NSApplication sharedApplication];
    NSMutableDictionary *appearances = [NSMutableDictionary dictionary];
    NSArray *selectors = ColorSelectors();
    NSArray *names = @[NSAppearanceNameAqua, NSAppearanceNameDarkAqua,
      NSAppearanceNameVibrantLight, NSAppearanceNameVibrantDark,
      NSAppearanceNameAccessibilityHighContrastAqua,
      NSAppearanceNameAccessibilityHighContrastDarkAqua,
      NSAppearanceNameAccessibilityHighContrastVibrantLight,
      NSAppearanceNameAccessibilityHighContrastVibrantDark];
    for (NSString *name in names) {
      NSAppearance *appearance = [NSAppearance appearanceNamed:name];
      if (!appearance) continue;
      [appearance performAsCurrentDrawingAppearance:^{
        NSMutableDictionary *colors = [NSMutableDictionary dictionary];
        NSMutableDictionary *unresolved = [NSMutableDictionary dictionary];
        for (NSString *selectorName in selectors) {
          SEL selector = NSSelectorFromString(selectorName);
          @try {
            id (*getter)(id, SEL) = (void *)[NSColor methodForSelector:selector];
            id value = getter(NSColor.class, selector);
            if ([value isKindOfClass:NSColor.class]) colors[selectorName] = Color(value);
          } @catch (NSException *e) { unresolved[selectorName] = e.reason ?: e.name; }
        }
        NSMutableArray *alternating = [NSMutableArray array];
        for (NSColor *color in NSColor.alternatingContentBackgroundColors)
          [alternating addObject:Color(color)];
        NSMutableDictionary *palettes = [NSMutableDictionary dictionary];
        for (NSColorList *list in NSColorList.availableColorLists) {
          NSMutableDictionary *entries = [NSMutableDictionary dictionary];
          for (NSString *key in list.allKeys) {
            NSColor *color = [list colorWithKey:key];
            if (color) entries[key] = Color(color);
          }
          palettes[list.name] = entries;
        }
        appearances[name] = @{ @"colors": colors, @"unresolved": unresolved,
          @"alternatingContentBackgroundColors": alternating, @"colorLists": palettes };
      }];
    }
    NSMutableDictionary *fonts = [NSMutableDictionary dictionary];
    NSDictionary *roles = @{
      @"system": Font([NSFont systemFontOfSize:0]),
      @"boldSystem": Font([NSFont boldSystemFontOfSize:0]),
      @"label": Font([NSFont labelFontOfSize:0]),
      @"menu": Font([NSFont menuFontOfSize:0]),
      @"menuBar": Font([NSFont menuBarFontOfSize:0]),
      @"message": Font([NSFont messageFontOfSize:0]),
      @"palette": Font([NSFont paletteFontOfSize:0]),
      @"titleBar": Font([NSFont titleBarFontOfSize:0]),
      @"toolTips": Font([NSFont toolTipsFontOfSize:0]),
      @"controlContent": Font([NSFont controlContentFontOfSize:0]),
      @"user": Font([NSFont userFontOfSize:0]),
      @"userFixedPitch": Font([NSFont userFixedPitchFontOfSize:0]),
      @"monospacedSystem": Font([NSFont monospacedSystemFontOfSize:0 weight:NSFontWeightRegular])
    };
    fonts[@"roles"] = roles;
    NSMutableDictionary *weights = [NSMutableDictionary dictionary];
    NSDictionary *weightValues = @{@"ultraLight": @(NSFontWeightUltraLight),
      @"thin": @(NSFontWeightThin), @"light": @(NSFontWeightLight),
      @"regular": @(NSFontWeightRegular), @"medium": @(NSFontWeightMedium),
      @"semibold": @(NSFontWeightSemibold), @"bold": @(NSFontWeightBold),
      @"heavy": @(NSFontWeightHeavy), @"black": @(NSFontWeightBlack)};
    for (NSString *name in weightValues)
      weights[name] = Font([NSFont systemFontOfSize:NSFont.systemFontSize
                                             weight:[weightValues[name] doubleValue]]);
    fonts[@"weights"] = weights;
    NSMutableDictionary *controls = [NSMutableDictionary dictionary];
    NSArray *sizes = @[@(NSControlSizeRegular), @(NSControlSizeSmall),
                      @(NSControlSizeMini), @(NSControlSizeLarge)];
    NSArray *sizeNames = @[@"regular", @"small", @"mini", @"large"];
    for (NSUInteger i = 0; i < sizes.count; ++i) {
      NSControlSize size = [sizes[i] unsignedIntegerValue];
      CGFloat fontSize = [NSFont systemFontSizeForControlSize:size];
      NSButton *button = [NSButton buttonWithTitle:@"Button" target:nil action:nil];
      button.controlSize = size;
      button.font = [NSFont systemFontOfSize:fontSize];
      [button sizeToFit];
      NSTextField *field = [[NSTextField alloc] initWithFrame:NSZeroRect];
      field.controlSize = size;
      field.font = [NSFont systemFontOfSize:fontSize];
      field.stringValue = @"Text";
      [field sizeToFit];
      controls[sizeNames[i]] = @{ @"font": Font(button.font),
        @"buttonSize": @[@(button.frame.size.width), @(button.frame.size.height)],
        @"textfieldSize": @[@(field.frame.size.width), @(field.frame.size.height)],
        @"scrollerLegacyWidth": @([NSScroller scrollerWidthForControlSize:size scrollerStyle:NSScrollerStyleLegacy]),
        @"scrollerOverlayWidth": @([NSScroller scrollerWidthForControlSize:size scrollerStyle:NSScrollerStyleOverlay]) };
    }
    NSWorkspace *workspace = NSWorkspace.sharedWorkspace;
    NSDictionary *result = @{ @"schema": @1,
      @"os": NSProcessInfo.processInfo.operatingSystemVersionString,
      @"colorSpace": @"sRGB; unpremultiplied RGBA; ARGB rounded to 8 bits",
      @"captureMethod": @"AppKit public APIs; appearance-local overrides; no global preference changes",
      @"appearances": appearances, @"fonts": fonts, @"controls": controls,
      @"environment": @{
        @"effectiveAppearance": NSApp.effectiveAppearance.name,
        @"reduceTransparency": @(workspace.accessibilityDisplayShouldReduceTransparency),
        @"increaseContrast": @(workspace.accessibilityDisplayShouldIncreaseContrast),
        @"differentiateWithoutColor": @(workspace.accessibilityDisplayShouldDifferentiateWithoutColor),
        @"reduceMotion": @(workspace.accessibilityDisplayShouldReduceMotion),
        @"scrollerStyle": @([NSScroller preferredScrollerStyle]),
        @"menuBarHeight": @(NSApp.mainMenu.menuBarHeight),
        @"doubleClickInterval": @(NSEvent.doubleClickInterval),
        @"caretBlinkPeriod": [NSUserDefaults.standardUserDefaults objectForKey:@"NSTextInsertionPointBlinkPeriod"] ?: NSNull.null }
    };
    NSError *error = nil;
    NSData *json = [NSJSONSerialization dataWithJSONObject:result
      options:NSJSONWritingPrettyPrinted | NSJSONWritingSortedKeys error:&error];
    if (!json) { fprintf(stderr, "%s\n", error.description.UTF8String); return 1; }
    fwrite(json.bytes, 1, json.length, stdout);
    putchar('\n');
  }
}
