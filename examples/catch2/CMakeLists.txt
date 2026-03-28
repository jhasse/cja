cmake_minimum_required(VERSION 3.15)
project(catch2_example LANGUAGES CXX)

include(../cpm/cmake/CPM.cmake)

CPMAddPackage(NAME Catch2
    URL https://github.com/catchorg/Catch2/archive/refs/tags/v3.13.0.tar.gz
    URL_HASH SHA256=650795f6501af514f806e78c554729847b98db6935e69076f36bb03ed2e985ef
)

add_executable(catch2_example test.cpp)
target_link_libraries(catch2_example Catch2::Catch2WithMain)

enable_testing()
add_test(catch2_example catch2_example)
