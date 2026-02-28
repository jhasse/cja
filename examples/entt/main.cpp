#include <entt/entt.hpp>

int main() {
    entt::registry registry;
    const entt::entity entity = registry.create();
    registry.emplace<int>(entity, 42);
    return registry.any_of<int>(entity) ? 0 : 1;
}
