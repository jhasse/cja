#include <iostream>
#include "math.hpp"

int main() {
    std::cout << "3 + 4 = " << math::add(3, 4) << std::endl;
    std::cout << "3 * 4 = " << math::multiply(3, 4) << std::endl;
    return 0;
}
