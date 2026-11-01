# Bundled with cja: a simplified version of CMake's check_language().
#
# CMake configures a test project to find a compiler for the language. cja
# only builds C, C++, Objective-C, Objective-C++ and assembly, all with its C
# and C++ compilers, so check_language() reports one of those or NOTFOUND for
# any other language. Projects then skip enable_language() for languages cja
# can't build.

include_guard(GLOBAL)

macro(check_language _cja_cl_lang)
  if(NOT DEFINED CMAKE_${_cja_cl_lang}_COMPILER)
    if("${_cja_cl_lang}" MATCHES "^(C|OBJC|ASM)$")
      set(CMAKE_${_cja_cl_lang}_COMPILER "${CMAKE_C_COMPILER}")
    elseif("${_cja_cl_lang}" MATCHES "^(CXX|OBJCXX)$")
      set(CMAKE_${_cja_cl_lang}_COMPILER "${CMAKE_CXX_COMPILER}")
    else()
      set(CMAKE_${_cja_cl_lang}_COMPILER NOTFOUND)
    endif()
    set(CMAKE_${_cja_cl_lang}_COMPILER "${CMAKE_${_cja_cl_lang}_COMPILER}"
      CACHE FILEPATH "${_cja_cl_lang} compiler")
  endif()
endmacro()
