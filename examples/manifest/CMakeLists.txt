cmake_minimum_required(VERSION 3.10)
project(manifest_example C)

# Add .manifest directly as source - cja auto-generates .rc and uses llvm-rc
add_executable(app main.c app.manifest)
