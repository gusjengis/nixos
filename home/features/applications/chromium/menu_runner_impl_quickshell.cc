// Copyright 2026 The Chromium Authors
// Use of this source code is governed by a BSD-style license that can be
// found in the LICENSE file.

#include "ui/views/controls/menu/menu_runner_impl_quickshell.h"

#include <poll.h>
#include <sys/socket.h>
#include <sys/un.h>
#include <unistd.h>

#include <cerrno>
#include <cstring>
#include <optional>
#include <string>
#include <utility>

#include "base/base64.h"
#include "base/environment.h"
#include "base/files/scoped_file.h"
#include "base/functional/bind.h"
#include "base/json/json_writer.h"
#include "base/memory/ref_counted_memory.h"
#include "base/posix/eintr_wrapper.h"
#include "base/strings/string_number_conversions.h"
#include "base/strings/utf_string_conversions.h"
#include "base/task/thread_pool.h"
#include "ui/base/accelerators/accelerator.h"
#include "ui/base/models/image_model.h"
#include "ui/gfx/image/image.h"
#include "ui/gfx/image/image_skia.h"
#include "ui/views/controls/menu/menu_runner_impl_adapter.h"

namespace views::internal {
namespace {

// -2 asks the UI thread to use Chromium's regular menu when the shell is not
// available. -1 means dismissed. Nonnegative values are snapshot action tokens.
int PresentMenu(std::string path, std::string request,
                std::shared_ptr<std::atomic<bool>> cancelled) {
  base::ScopedFD fd(socket(AF_UNIX, SOCK_STREAM | SOCK_CLOEXEC | SOCK_NONBLOCK, 0));
  sockaddr_un address{};
  address.sun_family = AF_UNIX;
  if (!fd.is_valid() || path.size() >= sizeof(address.sun_path)) {
    return -2;
  }
  std::memcpy(address.sun_path, path.c_str(), path.size() + 1);
  if (connect(fd.get(), reinterpret_cast<sockaddr*>(&address), sizeof(address))) {
    return -2;
  }
  request += '\n';
  size_t sent = 0;
  const auto deadline = base::TimeTicks::Now() + base::Seconds(2);
  while (sent < request.size() && !cancelled->load()) {
    const auto count = HANDLE_EINTR(send(fd.get(), request.data() + sent,
                                       request.size() - sent, MSG_NOSIGNAL));
    if (count > 0) {
      sent += count;
    } else if (count < 0 && (errno == EAGAIN || errno == EWOULDBLOCK) &&
               base::TimeTicks::Now() < deadline) {
      pollfd writable{fd.get(), POLLOUT, 0};
      HANDLE_EINTR(poll(&writable, 1, 50));
    } else {
      return -2;
    }
  }
  std::string response;
  while (!cancelled->load()) {
    pollfd readable{fd.get(), POLLIN, 0};
    if (HANDLE_EINTR(poll(&readable, 1, 100)) < 0) {
      return -1;
    }
    if (!readable.revents) {
      continue;
    }
    char buffer[64];
    const auto count = HANDLE_EINTR(recv(fd.get(), buffer, sizeof(buffer), 0));
    if (count <= 0) {
      return -1;
    }
    response.append(buffer, count);
    if (const auto newline = response.find('\n'); newline != std::string::npos) {
      int token = -1;
      return base::StringToInt(response.substr(0, newline), &token) ? token : -1;
    }
    if (response.size() > 64) {
      return -1;
    }
  }
  return -1;
}

}  // namespace

MenuRunnerImplQuickshell::MenuRunnerImplQuickshell(
    ui::MenuModel* model, base::RepeatingClosure on_closed)
    : model_(model->AsWeakPtr()), on_closed_(std::move(on_closed)) {}

MenuRunnerImplQuickshell::~MenuRunnerImplQuickshell() {
  if (cancelled_) {
    cancelled_->store(true);
  }
  if (fallback_) {
    fallback_->Release();
  }
}

bool MenuRunnerImplQuickshell::IsRunning() const {
  return running_ || (fallback_ && fallback_->IsRunning());
}

void MenuRunnerImplQuickshell::Release() {
  delete this;
}

bool MenuRunnerImplQuickshell::Snapshot(ui::MenuModel* model,
                                       base::ListValue& items, int depth,
                                       const ui::ColorProvider* color_provider) {
  if (depth > 16 || actions_.size() > 4096) {
    return false;
  }
  model->MenuWillShow();
  shown_models_.push_back(model->AsWeakPtr());
  for (size_t i = 0; i < model->GetItemCount(); ++i) {
    if (!model->IsVisibleAt(i)) {
      continue;
    }
    const auto type = model->GetTypeAt(i);
    // These require custom interactive Views rather than a standard menu row.
    if (type == ui::MenuModel::TYPE_BUTTON_ITEM ||
        type == ui::MenuModel::TYPE_ACTIONABLE_SUBMENU) {
      return false;
    }
    base::DictValue item;
    item.Set("text", base::UTF16ToUTF8(model->GetLabelAt(i)));
    item.Set("mnemonic", model->MayHaveMnemonicsAt(i));
    item.Set("isSeparator", type == ui::MenuModel::TYPE_SEPARATOR);
    item.Set("enabled", model->IsEnabledAt(i) && type != ui::MenuModel::TYPE_TITLE);
    item.Set("checkable", type == ui::MenuModel::TYPE_CHECK ||
                              type == ui::MenuModel::TYPE_RADIO);
    item.Set("checked", model->IsItemCheckedAt(i));
    const auto icon = model->GetIconAt(i);
    if (!icon.IsEmpty()) {
      const auto png = gfx::Image(icon.Rasterize(color_provider)).As1xPNGBytes();
      if (png->size()) {
        item.Set("icon", "data:image/png;base64," +
                             base::Base64Encode(base::span<const uint8_t>(*png)));
      }
    }
    ui::Accelerator accelerator;
    if (model->GetAcceleratorAt(i, &accelerator)) {
      item.Set("shortcut", base::UTF16ToUTF8(accelerator.GetShortcutText()));
    }
    item.Set("token", static_cast<int>(actions_.size()));
    actions_.push_back({model->AsWeakPtr(), i, model->GetCommandIdAt(i)});
    base::ListValue children;
    if (type == ui::MenuModel::TYPE_SUBMENU) {
      auto* submenu = model->GetSubmenuModelAt(i);
      if (!submenu || !Snapshot(submenu, children, depth + 1, color_provider)) {
        return false;
      }
    }
    item.Set("children", std::move(children));
    items.Append(std::move(item));
  }
  return true;
}

void MenuRunnerImplQuickshell::RunMenuAt(
    Widget* parent, MenuButtonController* button_controller,
    const gfx::Rect& bounds, MenuAnchorPosition anchor,
    ui::mojom::MenuSourceType source_type, int32_t run_types,
    gfx::NativeView native_view_for_gestures,
    std::optional<gfx::RoundedCornersF> corners,
    std::optional<std::string> histogram) {
  if (IsRunning() || !model_) {
    return;
  }
  if (fallback_) {
    fallback_->RunMenuAt(parent, button_controller, bounds, anchor, source_type,
                         run_types, native_view_for_gestures, corners, histogram);
    return;
  }
  auto run_fallback = base::BindOnce(
      [](base::WeakPtr<MenuRunnerImplQuickshell> self,
         base::WeakPtr<Widget> parent, const gfx::Rect& bounds,
         MenuAnchorPosition anchor, ui::mojom::MenuSourceType source_type,
         int32_t run_types) {
        if (!self || !parent || !self->model_) {
          return;
        }
        self->running_ = false;
        self->owner_observation_.Reset();
        self->CloseModels();
        self->fallback_ = new MenuRunnerImplAdapter(self->model_.get(), self->on_closed_);
        self->fallback_->RunMenuAt(parent.get(), nullptr, bounds, anchor,
                                  source_type, run_types);
      }, weak_factory_.GetWeakPtr(), parent->GetWeakPtr(), bounds, anchor,
      source_type, run_types);
  actions_.clear();
  shown_models_.clear();
  base::ListValue items;
  if (!Snapshot(model_.get(), items, 0, parent->GetColorProvider())) {
    std::move(run_fallback).Run();
    return;
  }
  base::DictValue request;
  request.Set("items", std::move(items));
  // Wayland deliberately lacks global window coordinates. The shell anchors
  // pointer menus at the compositor cursor, and keyboard menus at the owner.
  request.Set("keyboard", source_type == ui::mojom::MenuSourceType::kKeyboard ||
                              (run_types & MenuRunner::INVOKED_FROM_KEYBOARD));
  const auto owner_bounds = parent->GetWindowBoundsInScreen();
  request.Set("x", bounds.x() - owner_bounds.x());
  request.Set("y", bounds.bottom() - owner_bounds.y());
  std::string json;
  if (!base::JSONWriter::Write(request, &json)) {
    std::move(run_fallback).Run();
    return;
  }
  const auto runtime = base::Environment::Create()->GetVar("XDG_RUNTIME_DIR");
  if (!runtime) {
    std::move(run_fallback).Run();
    return;
  }
  running_ = true;
  closing_time_ = {};
  owner_observation_.Observe(parent);
  cancelled_ = std::make_shared<std::atomic<bool>>(false);
  base::ThreadPool::PostTaskAndReplyWithResult(
      FROM_HERE, {base::MayBlock(), base::TaskPriority::USER_BLOCKING},
      base::BindOnce(&PresentMenu, *runtime + "/chromium-quickshell-menu.sock",
                     std::move(json), cancelled_),
      base::BindOnce(
          [](base::WeakPtr<MenuRunnerImplQuickshell> self,
             base::OnceClosure fallback, int token) {
            if (!self) {
              return;
            }
            if (token == -2) {
              std::move(fallback).Run();
            } else {
              self->Finish(token);
            }
          }, weak_factory_.GetWeakPtr(), std::move(run_fallback)));
}

void MenuRunnerImplQuickshell::CloseModels() {
  auto models = std::move(shown_models_);
  for (auto it = models.rbegin(); it != models.rend(); ++it) {
    if (*it) {
      (*it)->MenuWillClose();
    }
  }
}

void MenuRunnerImplQuickshell::Finish(int token) {
  running_ = false;
  closing_time_ = base::TimeTicks::Now();
  owner_observation_.Reset();
  if (cancelled_) {
    cancelled_->store(true);
  }
  const auto weak = weak_factory_.GetWeakPtr();
  if (token >= 0 && static_cast<size_t>(token) < actions_.size()) {
    const Action action = actions_[token];
    if (action.model && action.index < action.model->GetItemCount() &&
        action.model->GetCommandIdAt(action.index) == action.command &&
        action.model->IsVisibleAt(action.index) && action.model->IsEnabledAt(action.index)) {
      const auto type = action.model->GetTypeAt(action.index);
      if (type == ui::MenuModel::TYPE_COMMAND || type == ui::MenuModel::TYPE_CHECK ||
          type == ui::MenuModel::TYPE_RADIO || type == ui::MenuModel::TYPE_HIGHLIGHTED) {
        action.model->ActivatedAt(action.index);
      }
    }
  }
  // Executing a command may destroy its menu runner. Match Views' ordering:
  // execute first, then notify surviving menu models that the menu closed.
  if (!weak) {
    return;
  }
  CloseModels();
  if (weak && on_closed_) {
    on_closed_.Run();
  }
}

void MenuRunnerImplQuickshell::Cancel() {
  if (fallback_) {
    fallback_->Cancel();
  } else if (running_) {
    weak_factory_.InvalidateWeakPtrs();
    Finish(-1);
  }
}

base::TimeTicks MenuRunnerImplQuickshell::GetClosingEventTime() const {
  return fallback_ ? fallback_->GetClosingEventTime() : closing_time_;
}

void MenuRunnerImplQuickshell::OnWidgetDestroying(Widget* widget) {
  Cancel();
}

}  // namespace views::internal
