#include "math.hpp"

#include <iostream>

static_assert(__cplusplus >= 202002L, "C++20 or later is required");

int main() {
    std::cout << "3 + 4 = " << math::add(3, 4) << std::endl;
    std::cout << "3 * 4 = " << math::multiply(3, 4) << std::endl;
    return 0;
}
