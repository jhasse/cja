cmake_minimum_required(VERSION 3.15)
project(freetype_example LANGUAGES CXX)

find_package(PkgConfig REQUIRED)
pkg_check_modules(FREETYPE REQUIRED freetype2)

add_library(mylib
    mylib.cpp
)

target_include_directories(mylib
    PUBLIC ${FREETYPE_INCLUDE_DIRS}
)

target_link_libraries(mylib
    PUBLIC ${FREETYPE_LIBRARIES}
)

add_executable(myapp
    main.cpp
)

target_link_libraries(myapp
    PRIVATE mylib
)
