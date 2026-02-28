cmake_minimum_required(VERSION 3.15)
project(cereal_example LANGUAGES CXX)

include(../cpm/cmake/CPM.cmake)

CPMAddPackage(
	NAME cereal
	URL https://github.com/USCiLab/cereal/archive/refs/tags/v1.3.2.tar.gz
	OPTIONS "SKIP_PORTABILITY_TEST ON" "JUST_INSTALL_CEREAL ON"
)

add_executable(cereal_example
    main.cpp
)

target_link_libraries(cereal_example
    PRIVATE cereal
)
