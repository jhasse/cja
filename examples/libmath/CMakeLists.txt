cmake_minimum_required(VERSION 3.10)
project(libmath_example)

add_library(math STATIC math.cpp)
target_compile_features(math PUBLIC cxx_std_11)
add_executable(calculator main.cpp)
target_compile_features(calculator PRIVATE cxx_std_20)
target_link_libraries(calculator PRIVATE math)
