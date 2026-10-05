cmake_minimum_required(VERSION 3.10)
project(win32_executable_example C)

# Build as a Windows GUI app (no console) in Release only.
# Debug keeps a console so printf output is visible.
add_executable(app main.c)
set_target_properties(app PROPERTIES WIN32_EXECUTABLE $<CONFIG:Release>)

if(WIN32)
  target_link_libraries(app user32)
endif()
