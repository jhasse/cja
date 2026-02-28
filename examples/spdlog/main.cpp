#include <spdlog/spdlog.h>

int main() {
    spdlog::set_pattern("[%T] [%^%l%$] %v");
    spdlog::info("Hello from spdlog example");
    return 0;
}
