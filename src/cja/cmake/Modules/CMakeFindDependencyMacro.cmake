# Bundled with cja: a simplified version of CMake's find_dependency().
#
# Forwards to find_package(), passing on QUIET and REQUIRED from the
# find_package() call that loaded the calling package config file. If the
# dependency isn't found, the calling package is marked as not found and the
# config file returns.

macro(find_dependency _cja_fd_dep)
  set(_cja_fd_args ${ARGN})
  if(${CMAKE_FIND_PACKAGE_NAME}_FIND_QUIETLY)
    list(APPEND _cja_fd_args QUIET)
  endif()
  if(${CMAKE_FIND_PACKAGE_NAME}_FIND_REQUIRED)
    list(APPEND _cja_fd_args REQUIRED)
  endif()
  find_package(${_cja_fd_dep} ${_cja_fd_args})
  if(NOT ${_cja_fd_dep}_FOUND)
    set(${CMAKE_FIND_PACKAGE_NAME}_NOT_FOUND_MESSAGE
      "${CMAKE_FIND_PACKAGE_NAME} could not be found because dependency ${_cja_fd_dep} could not be found.")
    set(${CMAKE_FIND_PACKAGE_NAME}_FOUND False)
    return()
  endif()
endmacro()
