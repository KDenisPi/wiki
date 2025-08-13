cmake_minimum_required(VERSION 3.12)

#project name
project(wparser)
enable_testing()

set(VER_MJR 0)
set(VER_MIN 1)

set(CMAKE_BIULD_TYPE Debug)
set(WPARSER_LIBS  ${EXTRA_LIBS})

include_directories(BEFORE
   ${PROJECT_SOURCE_DIR}/../thparty/rapidjson/include
)


#aux_source_directory(${PROJECT_SOURCE_DIR} PARS_SOURCES)

add_executable(wpars main.cpp prop_dict.cpp)
add_executable(test_sread test_sread_parser.cpp smallthings.cpp)
add_executable(test_props test_props_match.cpp)

target_link_libraries(wpars ${WPARSER_LIBS})

target_link_libraries(test_sread ${WPARSER_LIBS})

add_test(NAME test-cjson-lib COMMAND test_cjson)
add_test(NAME test-props COMMAND test_props)
