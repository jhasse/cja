cmake_minimum_required(VERSION 3.15)
project(qt5_example LANGUAGES CXX)

find_package(Qt5 REQUIRED COMPONENTS Core)

add_executable(qt5_hello
    main.cpp
)

target_link_libraries(qt5_hello PRIVATE Qt5::Core)
