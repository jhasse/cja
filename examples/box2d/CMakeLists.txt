cmake_minimum_required(VERSION 3.14)
project(Box2DExample LANGUAGES CXX)

include(FetchContent)

FetchContent_Declare(
    box2d
    GIT_REPOSITORY https://github.com/erincatto/box2d.git
    GIT_TAG v3.1.1
)

FetchContent_MakeAvailable(box2d)

add_executable(box2d_example main.cpp)
target_link_libraries(box2d_example PRIVATE box2d)
target_compile_features(box2d_example PRIVATE cxx_std_17)
