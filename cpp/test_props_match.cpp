/**
 * @file test_props_match.cpp
 * @author Denis Kudia (dkudja@gmail.com)
 * @brief
 * @version 0.1
 * @date 2025-08-08
 *
 * @copyright Copyright (c) 2025
 *
 */

#include <stdlib.h>
#include <iostream>
#include <string>
#include <memory>

#include "rapidjson/document.h"
#include "smallthings.h"

#include "prop_dict.h"
#include "item_reader.h"
#include "item_parser.h"

int main (int argc, char* argv[])
{
    int status = EXIT_FAILURE;
    if(argc < 3){
        std::cout << "File names are absent. app prop_dict.json item.json" << std::endl;
        exit(status);
    }

    char buffer[MAX_LINE_LENGTH]; // Declare a character array (buffer) to store the line

    std::unique_ptr<wiki::Properties> ptr_props = std::make_unique<wiki::Properties>();
    if(!ptr_props->load(std::string(argv[1]))){
        exit(status);
    }

    std::cout << argv[1] << " Props count: " << ptr_props->MemberCount() << std::endl;


    std::unique_ptr<wiki::ItemReader> ptr_reader = std::make_unique<wiki::ItemReader>();
    if(ptr_reader->init(std::string(argv[2]))){
        if(ptr_reader->next(buffer, MAX_LINE_LENGTH)){
            std::atomic_int sync;
            std::unique_ptr<wiki::ItemParser> ptr_item = std::make_unique<wiki::ItemParser>(0, &sync);
            if(ptr_item->load(buffer)){
                auto ptr_item_doc = ptr_item->get();
                auto v_claims = ptr_item_doc->FindMember("claims");

                if(v_claims != ptr_item_doc->MemberEnd()){
                    std::cout << "Name: " << v_claims->name.GetString() << " Type: " << v_claims->value.GetType() << " Count: "
                        << v_claims->value.MemberCount() << std::endl;

                    auto ptr_props_doc = ptr_props->get();

                    for(auto cl_v = v_claims->value.MemberBegin(); cl_v != v_claims->value.MemberEnd(); ++cl_v){
                        auto prop = ptr_props_doc->FindMember(cl_v->name.GetString());
                        std::cout << "Name: " << cl_v->name.GetString() << " "
                            << (prop!=ptr_props_doc->MemberEnd() ? prop->value[0].GetString() : " Unknown ") << std::endl;
                    }
                }
                else
                    std::cout << "No such member: " << "claims" << std::endl;
            }
            status = EXIT_SUCCESS;
        }
    }

    exit(status);
}