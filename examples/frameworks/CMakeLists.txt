cmake_minimum_required(VERSION 3.15)
project(frameworks_example LANGUAGES CXX OBJCXX)

find_library(MAC_CORETEXT CoreText)
find_library(MAC_COREFOUNDATION CoreFoundation)
if (NOT MAC_CORETEXT OR NOT MAC_COREFOUNDATION)
    message(FATAL_ERROR "Required framework not found")
endif()

add_executable(frameworks_example
    main.mm
)

target_link_libraries(frameworks_example
    PRIVATE ${MAC_CORETEXT} ${MAC_COREFOUNDATION}
)
