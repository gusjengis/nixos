// Run against the fully patched Hyprglass source, including generated protocol C:
// cc -I<source>/src -I<source>/src/item-helper toolbar-protocol-test.c
//    <source>/src/item-helper/hyprglass-item-v1-protocol.c $(pkg-config --cflags --libs wayland-server) -o toolbar-protocol-test
// Exercises commit latching and inert-object lifetime, not rendering geometry.
#include "item-helper/helper.c"
#include <assert.h>
#include <sys/socket.h>
#include <unistd.h>

int main(void) {
    int sockets[2];
    assert(socketpair(AF_UNIX, SOCK_STREAM, 0, sockets) == 0);
    struct wl_display* display = wl_display_create();
    assert(display && api_start(display) == 0);
    struct wl_client* client = wl_client_create(display, sockets[0]);
    assert(client);
    struct wl_resource* surface = wl_resource_create(client, &wl_surface_interface, 1, 0);
    struct wl_resource* manager = wl_resource_create(client, &hyprglass_item_manager_v1_interface, 3, 0);
    struct manager_object manager_data = {.resource = manager};
    wl_resource_set_user_data(manager, &manager_data);
    manager_handle_get_item(client, manager, 0, surface);
    struct item_object* item = find_active_item_for_surface(surface);
    assert(item);
    struct hyprglass_item_state current;

    item_handle_set_region(client, item->resource, 0, "apple-toolbar", 0, 0, wl_fixed_from_int(73), wl_fixed_from_int(36), wl_fixed_from_int(18));
    assert(api_get(surface, &current) && current.regions[0].width == 0);
    api_snapshot(surface);
    item_handle_set_region(client, item->resource, 0, "apple-toolbar-inactive", 0, 0, wl_fixed_from_int(36), wl_fixed_from_int(36), wl_fixed_from_int(18));
    api_apply(surface);
    assert(api_get(surface, &current));
    assert(strcmp(current.regions[0].preset, "apple-toolbar") == 0 && current.regions[0].width == 73);
    api_snapshot(surface); api_apply(surface);
    assert(api_get(surface, &current) && strcmp(current.regions[0].preset, "apple-toolbar-inactive") == 0);

    item_handle_set_region(client, item->resource, 16, "ignored", 0, 0, 1, 1, 0);
    item_handle_unset_region(client, item->resource, 0);
    assert(api_get(surface, &current) && current.regions[0].width == 36);
    api_snapshot(surface); api_apply(surface);
    assert(api_get(surface, &current) && current.regions[0].width == 0);

    api_stop();
    item_handle_set_region(client, item->resource, 0, "apple-toolbar", 0, 0, 1, 1, 0);
    assert(item->inert && !api_get(surface, &current));
    assert(api_start(display) == 0);
    manager_handle_get_item(client, manager, 0, surface);
    struct item_object* replacement = find_active_item_for_surface(surface);
    assert(replacement && replacement != item);
    wl_resource_destroy(surface);
    assert(replacement->inert && replacement->surface == NULL);
    item_handle_unset_region(client, replacement->resource, 0);
    wl_resource_destroy(item->resource);
    wl_resource_destroy(replacement->resource);
    wl_display_destroy_clients(display);
    api_stop();
    wl_display_destroy(display);
    close(sockets[1]);
    return 0;
}
