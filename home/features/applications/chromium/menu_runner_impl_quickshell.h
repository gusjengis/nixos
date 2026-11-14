// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#ifndef UI_VIEWS_CONTROLS_MENU_MENU_RUNNER_IMPL_QUICKSHELL_H_
#define UI_VIEWS_CONTROLS_MENU_MENU_RUNNER_IMPL_QUICKSHELL_H_

#include <atomic>
#include <memory>
#include <vector>

#include "base/functional/callback.h"
#include "base/memory/weak_ptr.h"
#include "base/scoped_observation.h"
#include "base/time/time.h"
#include "base/values.h"
#include "ui/base/models/menu_model.h"
#include "ui/views/controls/menu/menu_runner_impl_interface.h"
#include "ui/views/widget/widget.h"
#include "ui/views/widget/widget_observer.h"

namespace ui {
class ColorProvider;
}

namespace views::internal {

// The Linux equivalent of MenuRunnerImplMac: presentation is delegated to the
// desktop, while model ownership and command execution stay in the browser.
class MenuRunnerImplQuickshell : public MenuRunnerImplInterface,
                                public WidgetObserver {
 public:
  MenuRunnerImplQuickshell(ui::MenuModel* model,
                          base::RepeatingClosure on_closed);
  bool IsRunning() const override;
  void Release() override;
  void RunMenuAt(Widget* parent,
                 MenuButtonController* button_controller,
                 const gfx::Rect& bounds,
                 MenuAnchorPosition anchor,
                 ui::mojom::MenuSourceType source_type,
                 int32_t run_types,
                 gfx::NativeView native_view_for_gestures,
                 std::optional<gfx::RoundedCornersF> corners,
                 std::optional<std::string> histogram) override;
  void Cancel() override;
  base::TimeTicks GetClosingEventTime() const override;
  void OnWidgetDestroying(Widget* widget) override;

 private:
  struct Action {
    base::WeakPtr<ui::MenuModel> model;
    size_t index;
    int command;
  };
  ~MenuRunnerImplQuickshell() override;
  bool Snapshot(ui::MenuModel* model, base::ListValue& items, int depth,
                const ui::ColorProvider* color_provider);
  void Finish(int token);
  void CloseModels();

  base::WeakPtr<ui::MenuModel> model_;
  base::RepeatingClosure on_closed_;
  std::vector<Action> actions_;
  std::vector<base::WeakPtr<ui::MenuModel>> shown_models_;
  std::shared_ptr<std::atomic<bool>> cancelled_;
  MenuRunnerImplInterface* fallback_ = nullptr;
  bool running_ = false;
  base::TimeTicks closing_time_;
  base::ScopedObservation<Widget, WidgetObserver> owner_observation_{this};
  base::WeakPtrFactory<MenuRunnerImplQuickshell> weak_factory_{this};
};

}  // namespace views::internal

#endif  // UI_VIEWS_CONTROLS_MENU_MENU_RUNNER_IMPL_QUICKSHELL_H_
