#include <nlohmann/json.hpp>
#include <iostream>

int main() {
    nlohmann::json j;
    j["key"] = "value";
    std::cout << j.dump() << std::endl;
}
