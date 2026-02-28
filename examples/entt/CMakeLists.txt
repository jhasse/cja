cmake_minimum_required(VERSION 3.15)
project(entt_example LANGUAGES CXX)

include(../cpm/cmake/CPM.cmake)

CPMAddPackage(
	NAME EnTT
	URL https://github.com/skypjack/entt/archive/refs/tags/v3.12.2.tar.gz
	URL_HASH SHA1=2959a0fda580ac33ac5d559925907ce0ca4f605f
)

add_executable(entt_example
    main.cpp
)

target_link_libraries(entt_example PRIVATE EnTT::EnTT)
