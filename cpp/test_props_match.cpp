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
#include "receiver_easy.h"

int main (int argc, char* argv[])
{
    int status = EXIT_FAILURE;
    if(argc < 3){
        std::cout << "File names are absent. app prop_dict.json item.json" << std::endl;
        exit(status);
    }

    std::shared_ptr<char> buffer = std::shared_ptr<char>(new char[MAX_LINE_LENGTH]);// Declare a character array (buffer) to store the line

    std::shared_ptr<wiki::Properties> ptr_props = std::make_shared<wiki::Properties>();
    if(!ptr_props->load(std::string(argv[1]))){
        exit(status);
    }

    std::cout << argv[1] << " Props count: " << ptr_props->MemberCount() << std::endl;
/*
    std::vector<std::string> v_props = {"P31", "P50", "P101", "P136", "P921", "P425", "P569",\
            "P570", "P571", "P577", "P585", "P793", "P921", "P1191", "P2093", "P3150", "P3989", "P4647"\
        "P4647", "P9899", "P10673"};
*/
    std::vector<std::string> v_props = {"P31", "P50", "P98", "P101", "P106", "P136", "P569",\
            "P570", "P571", "P574", "P575", "P577", "P580", "P582", "P585", "P746", "P921", "P1191"\
            "P1317", "P1319", "P1326", "P1464", "P1619", "P2093", "P3150", "P3989", "P3999",\
            "P6949", "P7124", "P7125", "P9899", "P10135", "P10673"};


    ptr_props->load_important_property(v_props);

    auto p_found = ptr_props->is_important_property("P571");
    std::cout << " P571 Found: " << p_found << std::endl;

    std::unique_ptr<wiki::ItemReader> ptr_reader = std::make_unique<wiki::ItemReader>();
    if(ptr_reader->init(std::string(argv[2]))){
        if(ptr_reader->next(buffer.get(), MAX_LINE_LENGTH)){
            std::atomic_int sync;
            std::shared_ptr<char> fake_buff;
            std::shared_ptr<wiki::Receiver> receiver = std::make_shared<wiki::ReceiverEasy>();
            std::unique_ptr<wiki::ItemParser> ptr_item = std::make_unique<wiki::ItemParser>(0, &sync, fake_buff, ptr_props, receiver);
            if(ptr_item->load(buffer.get())){
                auto ptr_item_doc = ptr_item->get();

                auto itm = ptr_item->parse_item();
                if(!std::get<0>(itm).empty()){
                    std::cout << " Item ID: " << std::get<0>(itm) << " Label: " << std::get<1>(itm) << " Description: " << std::get<2>(itm) << std::endl;
                }

                auto v_claims = ptr_item_doc->FindMember("claims");
                if(v_claims != ptr_item_doc->MemberEnd()){
                    std::cout << "Name: " << v_claims->name.GetString() << " Type: " << v_claims->value.GetType() << " Count: "
                        << v_claims->value.MemberCount() << std::endl;

                    auto ptr_props_doc = ptr_props->get();
                    for(auto cl_v = v_claims->value.MemberBegin(); cl_v != v_claims->value.MemberEnd(); ++cl_v){
                        ptr_item->parse_claim(cl_v);
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