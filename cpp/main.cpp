/**
 * @file main.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-07
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <iostream>
#include <memory>

#include "prop_dict.h"
#include "item_reader.h"

using namespace std;

int main (int argc, char* argv[])
{
    if(argc < 2){
        std::cout << "Missing parameters." << std::endl << "wpars prop_dictionary.json" << std::endl;
        exit(EXIT_FAILURE);
    }

    std::shared_ptr<wiki::Properties> ptr_props = std::make_shared<wiki::Properties>();

    if(!ptr_props->load(std::string(argv[1]))){
        exit(EXIT_FAILURE);
    }

    exit(EXIT_SUCCESS);
}