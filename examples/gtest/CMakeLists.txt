cmake_minimum_required(VERSION 3.15)
project(gtest_example)

enable_testing()
find_package(GTest REQUIRED)

add_executable(sample_test
    sample_test.cpp
)

target_link_libraries(sample_test PRIVATE GTest::gtest_main)

add_test(NAME sample_test COMMAND sample_test)
