cmake_minimum_required(VERSION 4.0)
project(clang_tidy_example CXX)

add_executable(clang_tidy_example main.cpp foo.cpp)
set_target_properties(clang_tidy_example PROPERTIES CXX_CLANG_TIDY "clang-tidy;--use-color")
