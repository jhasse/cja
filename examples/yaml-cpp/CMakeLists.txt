cmake_minimum_required(VERSION 3.15)
project(yaml_cpp_example)

include(../cpm/cmake/CPM.cmake)

CPMAddPackage(
	NAME yaml_cpp
	VERSION 0.9.0
	URL "https://github.com/jbeder/yaml-cpp/releases/download/yaml-cpp-0.9.0/yaml-cpp-yaml-cpp-0.9.0.tar.gz"
)
add_executable(yaml_cpp_example
    main.cpp
)
target_link_libraries(yaml_cpp_example PRIVATE yaml-cpp)
