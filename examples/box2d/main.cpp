#include <box2d/box2d.h>
#include <iostream>

int main() {
    b2Version version = b2GetVersion();
    std::cout << "Box2D version: "
              << version.major << '.'
              << version.minor << '.'
              << version.revision << '\n';
}
