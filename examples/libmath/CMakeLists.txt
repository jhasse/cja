cmake_minimum_required(VERSION 3.10)
project(libmath_example)

add_library(math STATIC math.cpp)
add_executable(calculator main.cpp)
target_link_libraries(calculator PRIVATE math)
