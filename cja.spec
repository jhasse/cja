Name:           cja
Version:        0.10.1
Release:        %autorelease
Summary:        CMake-compatible build system that generates Ninja build files

# cja and its bundled ninja_syntax.py from Ninja are Apache-2.0. The CMake
# modules in cja/cmake/Modules/ (FindALSA, FindGTest, FindOpenSSL,
# GoogleTest) are taken from CMake and are BSD-3-Clause.
License:        Apache-2.0 AND BSD-3-Clause
URL:            https://github.com/jhasse/cja
Source:         %{pypi_source cja}

BuildArch:      noarch
BuildRequires:  python3-devel

# For the tests
BuildRequires:  bison
BuildRequires:  flex
BuildRequires:  gcc
BuildRequires:  gcc-c++
BuildRequires:  git-core
BuildRequires:  ninja-build
BuildRequires:  pkgconf-pkg-config
BuildRequires:  pkgconfig(zlib)
BuildRequires:  python3-pytest

Requires:       ninja-build

# Ninja's misc/ninja_syntax.py, extended with validation= support for
# validation nodes, which the ninja_syntax module from ninja-build lacks
Provides:       bundled(ninja_syntax)

%description
cja is a CMake-compatible build system that reads CMakeLists.txt files and
generates Ninja build files, without needing CMake. The build.ninja file is
written to the project root and uses relative paths, and tests run as part
of a phony "test" Ninja target instead of a separate tool like CTest.


%prep
%autosetup -p1 -n cja-%{version}


%generate_buildrequires
%pyproject_buildrequires


%build
%pyproject_wheel


%install
%pyproject_install
%pyproject_save_files -l cja
install -Dpm 0644 completions/cja.bash %{buildroot}%{bash_completions_dir}/cja


%check
# These examples download their dependencies with FetchContent or CPM
for example in box2d catch2 cereal cpm entt json spdlog yaml-cpp; do
  deselect="${deselect:-} --deselect tests/test_examples.py::test_example_builds[$example]"
done
%pytest $deselect


%files -f %{pyproject_files}
%doc README.md
%{_bindir}/cja
%{bash_completions_dir}/cja


%changelog
%autochangelog
