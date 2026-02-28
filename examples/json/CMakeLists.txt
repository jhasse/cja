cmake_minimum_required(VERSION 3.15)
project(json_example)

include(../cpm/cmake/CPM.cmake)

CPMAddPackage(
	NAME nlohmann_json
	VERSION 3.10.5
	URL "https://github.com/nlohmann/json/releases/download/v3.10.5/json.tar.xz"
)
add_executable(json_example
    main.cpp
)
target_link_libraries(json_example PRIVATE nlohmann_json)
