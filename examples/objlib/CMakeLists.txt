cmake_minimum_required(VERSION 3.15)

project(objlib_example CXX)

add_library(utils OBJECT utils.cpp)
add_executable(app main.cpp)
target_link_libraries(app utils)
