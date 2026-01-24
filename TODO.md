* set_target_properties(foo PROPERTIES INTERFACE_INCLUDE_DIRECTORIES ${CMAKE_CURRENT_SOURCE_DIR}/src/)
* target_link_libraries(foo PRIVATE $<$<AND:$<CXX_COMPILER_ID:GNU>,$<VERSION_LESS:$<CXX_COMPILER_VERSION>,9.0>>:stdc++fs>)
* CPMAddPackage
* get_directory_property(hasParent PARENT_DIRECTORY)
