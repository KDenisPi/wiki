/**
 * @file test_dict_class.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-09-24
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <string>
#include <iostream>

#include "dict_class.h"

using dict_2 = std::tuple<std::string, std::string>;

int main (int argc, char* argv[])
{
    const std::type_info& r1 = typeid(dict_2);
    std::cout << " Is tuple: " << (std::string(typeid(dict_2).name()).find("tuple") != std::string::npos) << "" << typeid(dict_2).name() << std::endl;
    std::cout << " " << typeid(std::string).name() << std::endl;


    //wiki::DictClass<dict_2> dict_2;

    exit(EXIT_SUCCESS);
}