cmake_minimum_required(VERSION 3.15)
project(spdlog_example LANGUAGES CXX)

include(../cpm/cmake/CPM.cmake)

CPMAddPackage(
    NAME spdlog
    URL https://github.com/gabime/spdlog/archive/refs/tags/v1.12.0.tar.gz
    DOWNLOAD_ONLY YES
)

add_executable(spdlog_example
    main.cpp
)

target_include_directories(spdlog_example
    PRIVATE ${spdlog_SOURCE_DIR}/include
)

target_compile_features(spdlog_example
    PRIVATE cxx_std_17
)
