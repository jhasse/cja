cmake_minimum_required(VERSION 3.15)
project(spdlog_example LANGUAGES CXX)

include(../cpm/cmake/CPM.cmake)

CPMAddPackage("https://github.com/fmtlib/fmt/releases/download/10.1.1/fmt-10.1.1.zip")
CPMAddPackage(
  NAME spdlog
  URL https://github.com/gabime/spdlog/archive/refs/tags/v1.12.0.tar.gz
  OPTIONS "SPDLOG_FMT_EXTERNAL 1"
)

add_executable(spdlog_example
    main.cpp
)

target_link_libraries(spdlog_example
    PRIVATE spdlog
)
